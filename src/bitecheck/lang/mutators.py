"""Mutation operators: turn changed lines into candidate mutants.

A mutant is a single, minimal, syntactically plausible edit. Operators are
ranked by *strength*: how unlikely the mutant is to be equivalent to the
original. With one mutant per line (the default), the strongest applicable
operator is used, so a survivor is good evidence that no test checks the line.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass

from .lexer import LangSpec, LexError, Token, tokenize


@dataclass(frozen=True)
class Mutant:
    path: str
    line: int
    start: int  # character offsets into the original file text
    end: int
    replacement: str
    operator: str
    rank: int  # lower = stronger
    original: str

    @property
    def id(self) -> str:
        return f"{self.path}:{self.line}:{self.start}:{self.operator}"

    def apply(self, text: str) -> str:
        return text[: self.start] + self.replacement + text[self.end:]

    def describe(self) -> str:
        orig = self.original.strip() or "(statement)"
        repl = self.replacement.strip() or "(removed)"
        return f"`{_short(orig)}` → `{_short(repl)}`"


def _short(s: str, n: int = 60) -> str:
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1] + "…"


# Operator ranks (lower = stronger, tried first).
R_STMT, R_RETURN, R_NEGATE_COND, R_LOGIC, R_CMP, R_ARITH, R_BOOL, R_NUMBER, R_BOUNDARY, R_INCDEC = range(10)

_CMP_FLIP = {"==": "!=", "!=": "==", "===": "!==", "!==": "===", "<": ">=", ">=": "<", ">": "<=", "<=": ">"}
_BOUNDARY = {"<": "<=", "<=": "<", ">": ">=", ">=": ">"}
_ARITH = {"+": "-", "-": "+", "*": "/", "/": "*", "%": "*", "//": "/", "**": "*",
          "+=": "-=", "-=": "+=", "*=": "/=", "/=": "*=", "<<": ">>", ">>": "<<"}
_LOGIC = {"&&": "||", "||": "&&", "and": "or", "or": "and", "??": "||"}
_INCDEC = {"++": "--", "--": "++"}

# Lines that are (almost) never meaningfully tested; mutating them produces noise.
_ARID = re.compile(
    r"^\s*(?:print\(|console\.(?:log|debug|info|warn|error|trace)\(|log(?:ger|ging)?\.\w+\(|"
    r"fmt\.(?:Print|Fprint|Sprint)|println!|eprintln!|dbg!|debug!|info!|warn!|trace!|"
    r"System\.(?:out|err)\.|Log\.\w\(|NSLog\(|puts\s|p\s|logger\.)",
)
_PRAGMA = re.compile(r"(?:bitecheck|pragma)\s*:\s*(?:ignore|no\s*mutate)", re.I)

_OPERAND_START_KINDS = ("name", "number", "string")


def generate(path: str, text: str, spec: LangSpec, lines: set[int]) -> list[Mutant]:
    """All candidate mutants on `lines` of `text`, strongest first per line."""
    if not lines:
        return []
    try:
        toks = tokenize(text, spec)
    except LexError:
        return []
    src_lines = text.split("\n")
    skip = {ln for ln in lines if ln - 1 < len(src_lines) and (
        _ARID.match(src_lines[ln - 1]) or _PRAGMA.search(src_lines[ln - 1]))}
    live = lines - skip
    out: list[Mutant] = []
    out += _token_mutants(path, toks, spec, live)
    if spec.family == "python":
        out += _python_stmt_mutants(path, text, live)
    else:
        out += _c_stmt_mutants(path, text, spec, live)
    # De-duplicate identical edits, keep deterministic order.
    seen, uniq = set(), []
    for m in sorted(out, key=lambda m: (m.line, m.rank, m.start, m.replacement)):
        key = (m.start, m.end, m.replacement)
        if key not in seen:
            seen.add(key)
            uniq.append(m)
    return uniq


def select(mutants: list[Mutant], per_line: int) -> list[Mutant]:
    """Keep the `per_line` strongest mutants on each line (0 = all)."""
    if per_line <= 0:
        return mutants
    by_line: dict[tuple[str, int], list[Mutant]] = {}
    for m in mutants:
        by_line.setdefault((m.path, m.line), []).append(m)
    chosen = []
    for key in sorted(by_line):
        chosen += sorted(by_line[key], key=lambda m: (m.rank, m.start))[:per_line]
    return chosen


# --- token-level -------------------------------------------------------------------

def _sig(toks: list[Token]) -> list[Token]:
    return [t for t in toks if t.kind not in ("comment", "nl")]


def _is_operand_end(t: Token | None) -> bool:
    return t is not None and (t.kind in _OPERAND_START_KINDS or t.text in (")", "]") or t.kind == "regex")


def _is_operand_start(t: Token | None) -> bool:
    return t is not None and (t.kind in _OPERAND_START_KINDS or t.text in ("(", "[", "!", "-", "+", "~"))


def _adjacent(a: Token, b: Token) -> bool:
    return a.end == b.start


def _token_mutants(path: str, toks: list[Token], spec: LangSpec, lines: set[int]) -> list[Mutant]:
    sig = _sig(toks)
    out: list[Mutant] = []
    t_true, t_false = spec.true_false
    for i, t in enumerate(sig):
        if t.line not in lines:
            continue
        prev = sig[i - 1] if i else None
        nxt = sig[i + 1] if i + 1 < len(sig) else None

        def mk(repl: str, op: str, rank: int, tok: Token = t) -> None:
            out.append(Mutant(path, tok.line, tok.start, tok.end, repl, op, rank, tok.text))

        if t.kind == "op":
            x = t.text
            binary = _is_operand_end(prev) and _is_operand_start(nxt)
            if x in ("<", ">") and _looks_generic(prev, t, nxt, spec):
                continue
            if x in (">>", ">>>") and spec.family not in ("python", "ruby", "php") and prev is not None and (
                prev.kind == "name" and _adjacent(prev, t) and (nxt is None or nxt.kind not in ("name", "number"))
            ):
                continue  # closing nested generics: Array<Array<number>>()
            if x in _CMP_FLIP and binary:
                mk(_CMP_FLIP[x], "negate-comparison", R_CMP)
                if x in _BOUNDARY:
                    mk(_BOUNDARY[x], "boundary", R_BOUNDARY)
            elif x in _LOGIC and binary:
                mk(_LOGIC[x], "swap-logical", R_LOGIC)
            elif x in _ARITH and binary:
                if x == "%" and prev is not None and prev.kind == "string" and spec.family == "python":
                    continue  # "%s" % value formatting
                if x in ("*", "**") and spec.family in ("c", "go", "rust") and not _spaced(prev, t, nxt):
                    continue  # likely pointer / deref
                if x == "+" and (prev and prev.kind == "string" or nxt and nxt.kind == "string"):
                    continue  # string concatenation: mutant is usually a type error, not a test
                mk(_ARITH[x], "swap-arithmetic", R_ARITH)
            elif x in ("+=", "-=", "*=", "/=") and prev is not None:
                mk(_ARITH[x], "swap-arithmetic", R_ARITH)
            elif x in _INCDEC and (prev and prev.kind == "name" or nxt and nxt.kind == "name"):
                mk(_INCDEC[x], "swap-increment", R_INCDEC)
            elif x == "!" and nxt is not None and _is_operand_start(nxt) and not (
                prev is not None and prev.kind == "name" and _adjacent(prev, t)  # rust macro!, swift/kotlin force-unwrap
            ):
                mk("", "remove-negation", R_NEGATE_COND)
        elif t.kind == "name":
            x = t.text
            if x == t_true and not _is_attr(prev):
                mk(t_false, "swap-boolean", R_BOOL)
            elif x == t_false and not _is_attr(prev):
                mk(t_true, "swap-boolean", R_BOOL)
            elif spec.logical_words and x in ("and", "or") and _is_operand_end(prev):
                mk(_LOGIC[x], "swap-logical", R_LOGIC)
            elif spec.logical_words and x == "not" and nxt is not None and nxt.text != "in" and not (
                prev is not None and prev.text in ("is",)
            ):
                # remove `not ` (including the following space)
                end = nxt.start
                out.append(Mutant(path, t.line, t.start, end, "", "remove-negation", R_NEGATE_COND, t.text + " "))
            elif spec.family == "python" and x == "in" and prev is not None and prev.text == "not":
                pass
        elif t.kind == "number":
            v = _int_value(t.text)
            if v is None or _is_attr(prev) or (prev is not None and prev.text in ("[",) and nxt and nxt.text in ("]", ":")):
                continue  # floats, hex flags, indexes like x[0] are noise-prone
            if prev is not None and prev.text == "-" and not _is_operand_end(sig[i - 2] if i >= 2 else None):
                continue  # negative literal
            repl = "1" if v == 0 else "0" if v == 1 else str(v + 1)
            mk(repl, "change-constant", R_NUMBER)
    return out


def _spaced(prev: Token | None, t: Token, nxt: Token | None) -> bool:
    return prev is not None and nxt is not None and prev.end < t.start and t.end < nxt.start


def _is_attr(prev: Token | None) -> bool:
    return prev is not None and prev.text in (".", "?.", "::")


def _int_value(text: str) -> int | None:
    t = text.replace("_", "")
    if not t.isdigit():
        return None
    try:
        return int(t)
    except ValueError:
        return None


def _looks_generic(prev: Token | None, t: Token, nxt: Token | None, spec: LangSpec) -> bool:
    if spec.family in ("python", "ruby", "php"):
        return False
    # Vec<T>, List<String>, foo::<u8>, Array<number>, x as Box<dyn Fn()>
    if prev is not None and nxt is not None and _adjacent(prev, t) and _adjacent(t, nxt):
        if t.text == "<" and prev.kind == "name" and nxt.kind == "name" and (
            prev.text[:1].isupper() or nxt.text[:1].isupper() or spec.family == "rust"
        ):
            return True
        if t.text == ">" and prev.kind == "name" and (prev.text[:1].isupper() or spec.family == "rust"):
            return True
    if t.text == ">" and prev is not None and prev.text == ">" and _adjacent(prev, t):
        return True
    if t.text == "<" and prev is not None and prev.text == "::":
        return True
    return False


# --- statement-level: Python (ast) --------------------------------------------------

def _python_stmt_mutants(path: str, text: str, lines: set[int]) -> list[Mutant]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    offsets = _line_offsets(text)
    out: list[Mutant] = []

    def span(node: ast.AST) -> tuple[int, int]:
        s = offsets[node.lineno - 1] + _byte_to_char(text, offsets[node.lineno - 1], node.col_offset)
        e = offsets[node.end_lineno - 1] + _byte_to_char(text, offsets[node.end_lineno - 1], node.end_col_offset)
        return s, e

    for node in ast.walk(tree):
        if not hasattr(node, "lineno") or node.lineno not in lines:
            continue
        if isinstance(node, ast.Expr) and isinstance(node.value, (ast.Call, ast.Await)):
            s, e = span(node)
            out.append(Mutant(path, node.lineno, s, e, "pass", "remove-call", R_STMT, text[s:e]))
        elif isinstance(node, ast.AugAssign):
            s, e = span(node)
            out.append(Mutant(path, node.lineno, s, e, "pass", "remove-statement", R_STMT, text[s:e]))
        elif isinstance(node, ast.Return) and node.value is not None and not (
            isinstance(node.value, ast.Constant) and node.value.value is None
        ):
            s, e = span(node)
            out.append(Mutant(path, node.lineno, s, e, "return None", "return-none", R_RETURN, text[s:e]))
        elif isinstance(node, (ast.If, ast.While)) and node.test.lineno in lines:
            s, e = span(node.test)
            if node.test.end_lineno == node.test.lineno:
                out.append(Mutant(path, node.lineno, s, e, f"not ({text[s:e]})", "negate-condition",
                                  R_NEGATE_COND, text[s:e]))
    return out


def _line_offsets(text: str) -> list[int]:
    offs = [0]
    for i, ch in enumerate(text):
        if ch == "\n":
            offs.append(i + 1)
    return offs


def _byte_to_char(text: str, line_start: int, byte_col: int) -> int:
    """ast col offsets are UTF-8 byte offsets; convert to character offsets."""
    line_end = text.find("\n", line_start)
    line = text[line_start: line_end if line_end >= 0 else len(text)]
    return len(line.encode("utf-8")[:byte_col].decode("utf-8", errors="ignore"))


# --- statement-level: C-like (line patterns) ----------------------------------------

_CALL_STMT = re.compile(r"^(\s*)((?:await\s+|try\s+|_\s*=\s*)?[A-Za-z_$][\w$]*(?:(?:\.|->|::|\?\.)[A-Za-z_$][\w$]*)*\s*\(.*\))\s*;?\s*$")
_NON_CALL_START = re.compile(
    r"^\s*(?:return|if|else|for|while|switch|case|func|fn|def|function|class|struct|let|const|var|val|"
    r"import|package|use|using|namespace|throw|new|super|this\s*\(|defer|go\s|select|match|assert|expect|"
    r"require|describe|it\(|test\(|print|console\.|log|fmt\.Print|System\.out)\b"
)
_IF_PAREN = re.compile(r"^(\s*(?:\}\s*)?(?:else\s+)?if\s*)\((.*)\)(\s*\{?\s*)$")
_IF_BARE = re.compile(r"^(\s*(?:\}\s*)?(?:else\s+)?if\s+)(.*?)(\s*\{\s*)$")
_RETURN = re.compile(r"^(\s*return\s+)(.+?)(;?\s*)$")


def _c_stmt_mutants(path: str, text: str, spec: LangSpec, lines: set[int]) -> list[Mutant]:
    offsets = _line_offsets(text)
    src_lines = text.split("\n")
    out: list[Mutant] = []
    try:
        toks = tokenize(text, spec)
    except LexError:
        return out
    # A line qualifies only if it contains no string/comment boundary weirdness we can't see.
    code_lines = {t.line for t in toks if t.kind in ("op", "name", "number")}
    for ln in sorted(lines):
        if ln - 1 >= len(src_lines) or ln not in code_lines:
            continue
        line = src_lines[ln - 1]
        base = offsets[ln - 1]
        m = _CALL_STMT.match(line)
        if m and not _NON_CALL_START.match(line) and _balanced(m.group(2)) and spec.family != "ruby":
            s = base + len(m.group(1))
            e = base + len(line.rstrip())
            repl = "" if spec.family in ("go", "python", "ruby", "swift", "kotlin") else ";"
            out.append(Mutant(path, ln, s, e, repl, "remove-call", R_STMT, line[len(m.group(1)):].rstrip()))
            continue
        paren_langs = ("c", "js", "java", "csharp", "php", "kotlin")
        mi = _IF_PAREN.match(line) if spec.family in paren_langs else _IF_BARE.match(line)
        if mi and _balanced(mi.group(2)) and mi.group(2).strip():
            cond = mi.group(2)
            s = base + len(mi.group(1)) + (1 if spec.family in paren_langs else 0)
            e = s + len(cond)
            repl = f"!({cond})" if spec.family != "ruby" else f"!({cond})"
            out.append(Mutant(path, ln, s, e, repl, "negate-condition", R_NEGATE_COND, cond))
            continue
        mr = _RETURN.match(line)
        if mr and spec.family in ("js",) and mr.group(2).strip() not in ("null", "undefined") and _balanced(mr.group(2)):
            s = base + len(mr.group(1))
            e = s + len(mr.group(2))
            out.append(Mutant(path, ln, s, e, "undefined", "return-none", R_RETURN, mr.group(2)))
    return out


def _balanced(expr: str) -> bool:
    depth = 0
    for ch in expr:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0
