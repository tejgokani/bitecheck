"""Lexers that tell code apart from strings and comments, for many languages.

Mutation operators only ever touch `op`, `name` and `number` tokens, so the
one job of these lexers is to be *right about what is not code*: strings
(including template literals, raw strings, triple-quoted and interpolated
strings), comments, regex literals and character/lifetime literals.

Python uses the stdlib tokenizer. Everything else goes through one
configurable lexer for the C/JS/Go/Rust/Ruby families.
"""

from __future__ import annotations

import io
import tokenize as _tok
from dataclasses import dataclass
from pathlib import PurePosixPath


@dataclass(frozen=True)
class Token:
    kind: str  # op | name | number | string | comment | regex | nl | other
    text: str
    start: int  # absolute character offset
    end: int
    line: int  # 1-based line of the token's first character


@dataclass(frozen=True)
class LangSpec:
    name: str
    family: str  # python | c | js | go | rust | ruby | php | swift | kotlin | java | csharp
    line_comments: tuple[str, ...] = ("//",)
    block_comment: tuple[str, str] | None = ("/*", "*/")
    single_quote_is_string: bool = False  # JS/PHP/Ruby: 'abc' is a string, not a char
    backtick_string: str | None = None  # "template" (JS ${}) | "raw" (Go)
    triple_quotes: bool = False  # Kotlin/Swift/Java text blocks """..."""
    regex_literals: bool = False  # JS/Ruby /re/
    rust_raw: bool = False  # r"..", r#".."#, b"..", lifetimes 'a
    csharp_strings: bool = False  # @"..", $"..", $@".."
    true_false: tuple[str, str] = ("true", "false")
    logical_words: bool = False  # and/or/not (Ruby, Python)


SPECS: dict[str, LangSpec] = {}


def _reg(exts: str, spec: LangSpec) -> None:
    for e in exts.split():
        SPECS[e] = spec


_reg(".py .pyi", LangSpec("python", "python", true_false=("True", "False"), logical_words=True))
_JS = LangSpec("javascript", "js", single_quote_is_string=True, backtick_string="template", regex_literals=True)
_reg(".js .mjs .cjs .jsx", _JS)
_reg(".ts .mts .cts .tsx", LangSpec("typescript", "js", single_quote_is_string=True,
                                    backtick_string="template", regex_literals=True))
_reg(".go", LangSpec("go", "go", backtick_string="raw"))
_reg(".rs", LangSpec("rust", "rust", rust_raw=True))
_reg(".java", LangSpec("java", "java", triple_quotes=True))
_reg(".kt .kts", LangSpec("kotlin", "kotlin", triple_quotes=True))
_reg(".swift", LangSpec("swift", "swift", triple_quotes=True))
_reg(".c .h .cc .cpp .cxx .hpp .hh", LangSpec("c", "c"))
_reg(".cs", LangSpec("csharp", "csharp", csharp_strings=True))
_reg(".php", LangSpec("php", "php", line_comments=("//", "#"), single_quote_is_string=True))
_reg(".rb", LangSpec("ruby", "ruby", line_comments=("#",), block_comment=None, single_quote_is_string=True,
                     regex_literals=True, logical_words=True))


def spec_for(path: str) -> LangSpec | None:
    return SPECS.get(PurePosixPath(path).suffix.lower())


class LexError(ValueError):
    pass


def tokenize(source: str, spec: LangSpec) -> list[Token]:
    if spec.family == "python":
        return _tokenize_python(source)
    return _CLexer(source, spec).run()


# --- Python ------------------------------------------------------------------------

def _tokenize_python(source: str) -> list[Token]:
    line_starts = [0]
    for i, ch in enumerate(source):
        if ch == "\n":
            line_starts.append(i + 1)

    def off(row: int, col: int) -> int:
        return line_starts[row - 1] + col

    out: list[Token] = []
    fstring_depth = 0
    fs_start = getattr(_tok, "FSTRING_START", -1)
    fs_end = getattr(_tok, "FSTRING_END", -2)
    ts_start = getattr(_tok, "TSTRING_START", -3)
    ts_end = getattr(_tok, "TSTRING_END", -4)
    try:
        for t in _tok.generate_tokens(io.StringIO(source).readline):
            if t.type in (fs_start, ts_start):
                fstring_depth += 1
                start = off(*t.start)
                continue
            if t.type in (fs_end, ts_end):
                fstring_depth -= 1
                if fstring_depth == 0:
                    out.append(Token("string", source[start:off(*t.end)], start, off(*t.end), _line_of(line_starts, start)))
                continue
            if fstring_depth:
                continue  # everything inside an f-string is treated as string
            kind = {
                _tok.OP: "op", _tok.NAME: "name", _tok.NUMBER: "number", _tok.STRING: "string",
                _tok.COMMENT: "comment", _tok.NEWLINE: "nl", _tok.NL: "nl",
            }.get(t.type, "other")
            if kind == "other":
                continue
            s, e = off(*t.start), off(*t.end)
            out.append(Token(kind, t.string, s, e, t.start[0]))
    except (_tok.TokenError, IndentationError, SyntaxError) as exc:
        raise LexError(f"python tokenize failed: {exc}") from exc
    return out


def _line_of(line_starts: list[int], offset: int) -> int:
    lo, hi = 0, len(line_starts) - 1
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if line_starts[mid] <= offset:
            lo = mid
        else:
            hi = mid - 1
    return lo + 1


# --- C-like families ---------------------------------------------------------------

_OPS = sorted(
    """>>>= === !== **= <<= >>= ... &&= ||= ??= ..= == != <= >= && || ++ -- += -= *= /= %= &= |= ^=
    -> => :: << >> ?? ?. := ** .. <=> !! ?: + - * / % = < > ! & | ^ ~ ? : ; , . ( ) [ ] { } @ # $ \\""".split(),
    key=len, reverse=True,
)

# Tokens after which a `/` starts a regex literal rather than a division.
_REGEX_PREV_OPS = set("( , = : [ ! & | ? { } ; + - * % < > ~ ^".split()) | {
    "==", "!=", "===", "!==", "&&", "||", "=>", "return", "typeof", "case", "do", "else", "in",
    "of", "new", "delete", "void", "throw", "yield", "await", "when", "if", "unless", "and", "or", "not",
}


class _CLexer:
    def __init__(self, src: str, spec: LangSpec):
        self.s = src
        self.spec = spec
        self.i = 0
        self.line = 1
        self.out: list[Token] = []

    def emit(self, kind: str, start: int, line: int) -> None:
        self.out.append(Token(kind, self.s[start:self.i], start, self.i, line))

    def _advance_to(self, j: int) -> None:
        self.line += self.s.count("\n", self.i, j)
        self.i = j

    def prev_sig(self) -> Token | None:
        for t in reversed(self.out):
            if t.kind not in ("comment", "nl"):
                return t
        return None

    def run(self) -> list[Token]:
        s, n = self.s, len(self.s)
        while self.i < n:
            c = s[self.i]
            start, line = self.i, self.line
            if c == "\n":
                self.i += 1
                self.line += 1
                self.out.append(Token("nl", "\n", start, self.i, line))
                continue
            if c in " \t\r\f\v":
                self.i += 1
                continue
            # comments
            lc = next((m for m in self.spec.line_comments if s.startswith(m, self.i)), None)
            if lc and not (lc == "#" and self.spec.family == "php" and s.startswith("#[", self.i)):
                j = s.find("\n", self.i)
                self._advance_to(n if j < 0 else j)
                self.emit("comment", start, line)
                continue
            bc = self.spec.block_comment
            if bc and s.startswith(bc[0], self.i):
                j = s.find(bc[1], self.i + len(bc[0]))
                if j < 0:
                    raise LexError(f"unterminated block comment at line {line}")
                self._advance_to(j + len(bc[1]))
                self.emit("comment", start, line)
                continue
            if self.spec.family == "ruby" and c == "=" and s.startswith("=begin", self.i) and (
                self.i == 0 or s[self.i - 1] == "\n"
            ):
                j = s.find("\n=end", self.i)
                self._advance_to(n if j < 0 else j + 5)
                self.emit("comment", start, line)
                continue
            # prefixed strings: rust raw/byte, c# verbatim/interpolated
            if self.spec.rust_raw and c in "rb" and self._rust_prefixed(start, line):
                continue
            if self.spec.csharp_strings and c in "@$" and self._csharp_prefixed(start, line):
                continue
            if c.isalpha() or c == "_" or (c == "$" and self.spec.family in ("js", "php")):
                j = self.i + 1
                while j < n and (s[j].isalnum() or s[j] == "_" or s[j] == "$"):
                    j += 1
                if self.spec.family == "ruby" and j < n and s[j] in "?!" and not s.startswith("!=", j):
                    j += 1  # predicate?/bang! method names
                self.i = j
                self.emit("name", start, line)
                continue
            if c.isdigit() or (c == "." and self.i + 1 < n and s[self.i + 1].isdigit()):
                self._number()
                self.emit("number", start, line)
                continue
            if c == '"':
                if self.spec.triple_quotes and s.startswith('"""', self.i):
                    j = s.find('"""', self.i + 3)
                    if j < 0:
                        raise LexError(f"unterminated text block at line {line}")
                    self._advance_to(j + 3)
                else:
                    self._quoted('"')
                self.emit("string", start, line)
                continue
            if c == "'":
                if self.spec.single_quote_is_string:
                    self._quoted("'")
                    self.emit("string", start, line)
                    continue
                if self.spec.rust_raw and self._rust_lifetime():
                    self.emit("name", start, line)
                    continue
                self._quoted("'")
                self.emit("string", start, line)  # char literal
                continue
            if c == "`" and self.spec.backtick_string:
                if self.spec.backtick_string == "raw":
                    j = s.find("`", self.i + 1)
                    if j < 0:
                        raise LexError(f"unterminated raw string at line {line}")
                    self._advance_to(j + 1)
                else:
                    self._template()
                self.emit("string", start, line)
                continue
            if c == "/" and self.spec.regex_literals and self._regex_allowed():
                if self._regex():
                    self.emit("regex", start, line)
                    continue
            if self.spec.family == "ruby" and c == ":" and self.i + 1 < n and (s[self.i + 1].isalpha() or s[self.i + 1] == "_"):
                j = self.i + 1
                while j < n and (s[j].isalnum() or s[j] in "_?!"):
                    j += 1
                self.i = j
                self.emit("string", start, line)  # symbol
                continue
            op = next((o for o in _OPS if s.startswith(o, self.i)), None)
            if op:
                self.i += len(op)
                self.emit("op", start, line)
                continue
            self.i += 1
            self.emit("other", start, line)
        return self.out

    # helpers ------------------------------------------------------------------------
    def _number(self) -> None:
        s, n = self.s, len(self.s)
        j = self.i
        if s.startswith(("0x", "0X", "0b", "0B", "0o", "0O"), j):
            j += 2
            while j < n and (s[j].isalnum() or s[j] == "_"):
                j += 1
        else:
            while j < n and (s[j].isdigit() or s[j] == "_"):
                j += 1
            if j < n and s[j] == "." and j + 1 < n and s[j + 1].isdigit():
                j += 1
                while j < n and (s[j].isdigit() or s[j] == "_"):
                    j += 1
            if j < n and s[j] in "eE" and j + 1 < n and (s[j + 1].isdigit() or s[j + 1] in "+-"):
                j += 2
                while j < n and s[j].isdigit():
                    j += 1
            while j < n and (s[j].isalnum()):  # suffixes: 10u32, 1.0f, 5L, 3n
                j += 1
        self.i = j

    def _quoted(self, q: str) -> None:
        s, n = self.s, len(self.s)
        j = self.i + 1
        while j < n:
            ch = s[j]
            if ch == "\\":
                j += 2
                continue
            if ch == q:
                self._advance_to(j + 1)
                return
            if ch == "\n" and q == "'" and not self.spec.single_quote_is_string:
                break
            j += 1
        raise LexError(f"unterminated string at line {self.line}")

    def _template(self) -> None:
        """JS template literal with ${...} nesting (which may contain strings and templates)."""
        s, n = self.s, len(self.s)
        j = self.i + 1
        while j < n:
            ch = s[j]
            if ch == "\\":
                j += 2
                continue
            if ch == "`":
                self._advance_to(j + 1)
                return
            if ch == "$" and j + 1 < n and s[j + 1] == "{":
                depth = 1
                j += 2
                while j < n and depth:
                    ch = s[j]
                    if ch in "\"'":
                        k = j + 1
                        while k < n and s[k] != ch:
                            k += 2 if s[k] == "\\" else 1
                        j = k + 1
                        continue
                    if ch == "`":
                        save_i, save_line = self.i, self.line
                        self.i, self.line = j, 0
                        self._template()
                        j = self.i
                        self.i, self.line = save_i, save_line
                        continue
                    if ch == "{":
                        depth += 1
                    elif ch == "}":
                        depth -= 1
                    j += 1
                continue
            j += 1
        raise LexError(f"unterminated template literal at line {self.line}")

    def _regex_allowed(self) -> bool:
        prev = self.prev_sig()
        if prev is None:
            return True
        if prev.kind == "op":
            return prev.text in _REGEX_PREV_OPS and prev.text not in (")", "]", "}")
        if prev.kind == "name":
            return prev.text in _REGEX_PREV_OPS
        return False

    def _regex(self) -> bool:
        s, n = self.s, len(self.s)
        j = self.i + 1
        in_class = False
        while j < n:
            ch = s[j]
            if ch == "\n":
                return False
            if ch == "\\":
                j += 2
                continue
            if ch == "[":
                in_class = True
            elif ch == "]":
                in_class = False
            elif ch == "/" and not in_class:
                j += 1
                while j < n and s[j].isalpha():
                    j += 1
                self.i = j
                return True
            j += 1
        return False

    def _rust_prefixed(self, start: int, line: int) -> bool:
        s = self.s
        j = self.i
        if s.startswith("br", j) or s.startswith("rb", j):
            j += 2
        elif s[j] in "rb":
            j += 1
        raw = "r" in s[self.i:j]
        hashes = 0
        while raw and j < len(s) and s[j] == "#":
            hashes += 1
            j += 1
        if j >= len(s) or s[j] not in "\"'":
            return False
        if s[j] == "'" and not raw:  # b'x' byte literal
            self.i = j
            self._quoted("'")
            self.emit("string", start, line)
            return True
        if s[j] != '"':
            return False
        if raw:
            close = '"' + "#" * hashes
            k = s.find(close, j + 1)
            if k < 0:
                raise LexError(f"unterminated raw string at line {line}")
            self._advance_to(k + len(close))
        else:
            self.i = j
            self._quoted('"')
        self.emit("string", start, line)
        return True

    def _rust_lifetime(self) -> bool:
        s = self.s
        j = self.i + 1
        if j < len(s) and (s[j].isalpha() or s[j] == "_"):
            k = j
            while k < len(s) and (s[k].isalnum() or s[k] == "_"):
                k += 1
            if k < len(s) and s[k] == "'":
                return False  # 'a' is a char literal
            self.i = k
            return True
        return False

    def _csharp_prefixed(self, start: int, line: int) -> bool:
        s = self.s
        j = self.i
        while j < len(s) and s[j] in "@$":
            j += 1
        if j == self.i or j >= len(s) or s[j] != '"' or j - self.i > 2:
            return False
        verbatim = "@" in s[self.i:j]
        if verbatim:
            k = j + 1
            while k < len(s):
                if s[k] == '"':
                    if k + 1 < len(s) and s[k + 1] == '"':
                        k += 2
                        continue
                    break
                k += 1
            self._advance_to(k + 1)
        else:
            self.i = j
            self._quoted('"')
        self.emit("string", start, line)
        return True
