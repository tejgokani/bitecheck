"""Lexer and mutation-operator tests: the parts that must never be wrong."""

import ast

import pytest

from bitecheck.lang import lexer, mutators


def code_tokens(src, ext):
    spec = lexer.spec_for("x" + ext)
    return [t.text for t in lexer.tokenize(src, spec) if t.kind in ("op", "name", "number")]


def muts(src, ext, lines=None, per_line=0):
    spec = lexer.spec_for("f" + ext)
    lines = lines or set(range(1, src.count("\n") + 2))
    return mutators.select(mutators.generate("f" + ext, src, spec, lines), per_line)


def applied(src, ext, **kw):
    return [m.apply(src) for m in muts(src, ext, **kw)]


# --- lexer: strings / comments are never code ---------------------------------------

@pytest.mark.parametrize("src,ext,forbidden", [
    ('x = "a + b" # c - d\n', ".py", {"b", "c", "d"}),
    ("x = f'{a + b}'\n", ".py", {"a", "b"}),
    ('x = """\n1 + 2\n"""\n', ".py", {"1", "2"}),
    ("const s = `a ${b + `c ${d - e}`} f`; // g + h\n", ".js", {"b", "d", "e", "g", "h"}),
    ("const r = /a+b/g.test(x); y = a / b / c\n", ".js", {"+"}),
    ("let a = 'it\\'s - ok'; /* x * y */\n", ".ts", {"x", "y", "it"}),
    ('s := `raw \\n + x`; t := "a" + b\n', ".go", {"raw", "x"}),
    ('let s = r#"he said "1 + 2""#; fn f<\'a>(x: &\'a str) -> u8 { 1 }\n', ".rs", {"he", "2"}),
    ("char c = '+'; String t = \"\"\"\n a < b\n\"\"\";\n", ".java", {"a", "b"}),
    ('var s = @"C:\\a + b"; var t = $"{x + y}";\n', ".cs", {"b", "x", "y"}),
    ("x = 'a' + b # comment - here\n=begin\n1 + 2\n=end\n", ".rb", {"comment", "here", "1", "2"}),
    ("$x = 'a' . $b; # skip + me\n// and - me\n", ".php", {"skip", "me"}),
])
def test_strings_and_comments_are_not_code(src, ext, forbidden):
    toks = set(code_tokens(src, ext))
    assert not (toks & forbidden), toks & forbidden


def test_rust_lifetime_vs_char():
    spec = lexer.spec_for("a.rs")
    toks = lexer.tokenize("fn f<'a>(c: char) { let x = 'z'; }", spec)
    kinds = {t.text: t.kind for t in toks}
    assert kinds["'a"] == "name" and kinds["'z'"] == "string"


def test_line_numbers_are_correct():
    src = 'a = 1\ns = """\nx\n"""\nb = 2\n'
    toks = lexer.tokenize(src, lexer.spec_for("x.py"))
    assert next(t for t in toks if t.text == "b").line == 5
    js = "a\n`x\ny`\nb\n"
    toks = lexer.tokenize(js, lexer.spec_for("x.js"))
    assert next(t for t in toks if t.text == "b").line == 4


def test_unterminated_string_is_lex_error():
    with pytest.raises(lexer.LexError):
        lexer.tokenize('x = "abc\n', lexer.spec_for("a.go"))


def test_unknown_extension():
    assert lexer.spec_for("README.md") is None


# --- mutators ---------------------------------------------------------------------------

def test_python_mutants_are_all_valid_syntax():
    src = (
        "def f(a, b, items):\n"
        "    if a < b and not items:\n"
        "        return a + b * 2\n"
        "    total = 0\n"
        "    for x in items:\n"
        "        total += x % 3\n"
        "    save(total)\n"
        "    return total == 10 or False\n"
    )
    out = applied(src, ".py")
    assert len(out) >= 12
    for m in out:
        ast.parse(m)  # every mutant must still parse


def test_python_specific_operators():
    src = "def f(x):\n    if x > 0:\n        log_it(x)\n    return x\n"
    ops = {m.operator for m in muts(src, ".py")}
    assert {"negate-condition", "remove-call", "return-none", "negate-comparison", "boundary"} <= ops


def test_one_per_line_picks_strongest():
    src = "def f(a, b):\n    return a + b\n"
    chosen = muts(src, ".py", lines={2}, per_line=1)
    assert len(chosen) == 1 and chosen[0].operator == "return-none"


def test_string_concat_and_percent_format_skipped():
    src = 'msg = "a" + name\nline = "%s" % x\n'
    assert all(m.operator != "swap-arithmetic" for m in muts(src, ".py"))


def test_arid_lines_and_pragma_skipped():
    src = "print(a + b)\nconsole.log(a - b)\nx = a + b  # bitecheck: ignore\n"
    assert muts(src, ".py", lines={1, 3}) == []
    assert muts("console.log(a - b);\n", ".js") == []


def test_js_operators_and_statements():
    src = (
        "function f(a, b) {\n"
        "  if (a === b && ok) {\n"
        "    save(a);\n"
        "  }\n"
        "  return a - b;\n"
        "}\n"
    )
    ops = {(m.line, m.operator) for m in muts(src, ".js")}
    assert (2, "negate-condition") in ops and (2, "negate-comparison") in ops and (2, "swap-logical") in ops
    assert (3, "remove-call") in ops and (5, "return-none") in ops and (5, "swap-arithmetic") in ops
    neg = next(m for m in muts(src, ".js") if m.operator == "negate-condition")
    assert neg.apply(src).splitlines()[1] == "  if (!(a === b && ok)) {"


def test_generics_and_unary_left_alone():
    ts = "const m: Map<string, Array<number>> = new Map<string, Array<number>>();\nconst y = -x;\n"
    assert [m for m in muts(ts, ".ts") if m.original in ("<", ">")] == []
    assert [m for m in muts(ts, ".ts") if m.operator == "swap-arithmetic"] == []
    rs = "let v: Vec<u8> = Vec::<u8>::new(); println!(\"{}\", x); let p = *ptr;\n"
    assert [m for m in muts(rs, ".rs") if m.original in ("<", ">", "!", "*")] == []


def test_go_mutants():
    src = "func Add(a, b int) int {\n\tif a > b {\n\t\tlog.Fatal(\"x\")\n\t}\n\treturn a + b\n}\n"
    ms = muts(src, ".go")
    neg = next(m for m in ms if m.operator == "negate-condition")
    assert neg.apply(src).splitlines()[1] == "\tif !(a > b) {"
    assert any(m.operator == "swap-arithmetic" and m.line == 5 for m in ms)


def test_numbers():
    src = "x = 0\ny = 1\nz = 41\nw = 3.5\nv = items[0]\nn = -1\n"
    reps = {m.line: m.replacement for m in muts(src, ".py") if m.operator == "change-constant"}
    assert reps == {1: "1", 2: "0", 3: "42"}


def test_mutants_only_on_requested_lines():
    src = "a = 1 + 2\nb = 3 + 4\n"
    assert {m.line for m in muts(src, ".py", lines={2})} == {2}


def test_unicode_offsets_python():
    src = 'def f(x):\n    s = "héllo"; return x + 1\n'
    for m in muts(src, ".py"):
        ast.parse(m.apply(src))


def test_unparseable_file_yields_nothing():
    assert muts('x = "unterminated\n', ".go") == []


def test_error_path_operators():
    py = "def f(x):\n    if x < 0:\n        raise ValueError(x)\n    return x\n"
    assert any(m.operator == "remove-raise" and m.apply(py).splitlines()[2].strip() == "pass" for m in muts(py, ".py"))
    js = "function f(x) {\n  if (x < 0) {\n    throw new RangeError('neg');\n  }\n  return x;\n}\n"
    assert any(m.operator == "remove-raise" and m.line == 3 for m in muts(js, ".js"))
    go = 'func P(n int) (int, error) {\n\tif n < 1 {\n\t\treturn 0, fmt.Errorf("bad %d", n)\n\t}\n\treturn n, nil\n}\n'
    drop = [m for m in muts(go, ".go") if m.operator == "drop-error"]
    assert len(drop) == 1 and drop[0].apply(go).splitlines()[2] == "\t\treturn 0, nil"


def test_two_per_line_prefers_distinct_operators():
    src = "def f(a, b):\n    if a > b:\n        return 1\n"
    chosen = muts(src, ".py", lines={2}, per_line=2)
    assert len(chosen) == 2 and len({m.operator for m in chosen}) == 2


def test_regex_mutations_js_and_python():
    js = "export const slug = (t) => t.replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');\n"
    reps = sorted((m.operator, m.apply(js).split("=>")[1].strip()) for m in muts(js, ".js") if m.operator.startswith("regex"))
    joined = " ".join(r for _, r in reps)
    assert "/[a-z0-9]+/g" in joined          # class inverted
    assert "/[^a-z0-9]/g" in joined          # quantifier dropped
    assert "/-+|-+$/g" in joined             # anchor dropped
    py = 'import re\nWORD = re.compile(r"^[a-z]+$")\nx = "not a [regex]+"\n'
    ops = {(m.line, m.operator) for m in muts(py, ".py")}
    assert (2, "regex-anchor") in ops and (2, "regex-quantifier") in ops
    assert not any(line == 3 for line, _ in ops)  # ordinary strings untouched


def test_per_line_picks_distinct_families():
    src = "def f(d):\n    if d.weekday() < 5:\n        return 1\n"
    chosen = muts(src, ".py", lines={2}, per_line=2)
    fams = {mutators.FAMILY[m.operator] for m in chosen}
    assert fams == {"invert", "constant"} or fams == {"invert", "boundary"}, chosen
