"""Goalpost, tamper, deps and claims probes, end to end."""

import json

import pytest
from conftest import CART_FEATURE, CART_TEST_V1, CART_V1, PYTEST, STRONG_TEST, WEAK_TEST, check_json, codes, git, make_repo, probe, write

from bitecheck.probes import claims, deps

# --- goalpost ---------------------------------------------------------------------------


def test_goalpost_moved(cart):
    write(cart, {"cart.py": CART_V1_BROKEN, "test_cart.py": CART_TEST_V1.replace("== 11", "== 12")})
    proc, doc = check_json(cart, "--probes", "goalpost")
    assert proc.returncode == 1 and "GOALPOST_MOVED" in codes(doc)


CART_V1_BROKEN = "def subtotal(items):\n    return sum(p * q for p, q in items) + 1\n"


def test_tests_only_change_has_no_cross_runs(cart):
    write(cart, {"test_cart.py": CART_TEST_V1 + "\n\ndef test_more():\n    assert True\n"})
    _, doc = check_json(cart, "--probes", "goalpost")
    assert set(probe(doc, "goalpost")["runs"]) == {"head", "base"}


# --- tamper -----------------------------------------------------------------------------

@pytest.mark.parametrize("files,code", [
    ({"test_cart.py": CART_TEST_V1.replace("def test_subtotal", "@pytest.mark.skip\ndef test_subtotal")}, "TESTS_SKIPPED"),
    ({"web.test.js": "it.only('x', () => {})\n"}, "TESTS_FOCUSED"),
    ({"test_cart.py": "from cart import subtotal\n\n\ndef test_subtotal():\n    pass\n"}, "ASSERTIONS_REMOVED"),
    ({"cart.py": CART_V1 + "\nx = 1  # type: ignore\n"}, "CHECKS_SUPPRESSED"),
    ({"cart.py": CART_V1 + "\ntry:\n    import foo\nexcept Exception:\n    pass\n"}, "ERRORS_SWALLOWED"),
    ({".github/workflows/ci.yml": "steps:\n  - run: pytest || true\n"}, "GATE_LOOSENED"),
    ({".bitecheck.toml": "min_score = 0\n"}, "CONFIG_EDITED"),
    ({"__snapshots__/a.snap": "x"}, "SNAPSHOTS_REWRITTEN"),
    ({"cart.py": CART_V1 + "\ndef leap(y):\n    if y == 1900:\n        return 29\n    return 28\n",
      "test_cart.py": CART_TEST_V1 + "\n\ndef test_leap():\n    from cart import leap\n    assert leap(1900) == 29\n"},
     "SPECIAL_CASE_SUSPECT"),
    ({"cart.py": CART_V1 + "\nPAD = 1  # bitecheck: ignore\n"}, "CHECKS_SUPPRESSED"),
])
def test_tamper_rules(cart, files, code):
    write(cart, files)
    _, doc = check_json(cart, "--probes", "tamper")
    assert code in codes(doc), probe(doc, "tamper")["findings"]


def test_coverage_threshold_lowered(tmp_path):
    repo = make_repo(tmp_path, {"pyproject.toml": "[tool.coverage.report]\nfail_under = 90\n"})
    write(repo, {"pyproject.toml": "[tool.coverage.report]\nfail_under = 40\n"})
    _, doc = check_json(repo, "--probes", "tamper")
    gate = next(f for f in probe(doc, "tamper")["findings"] if f["code"] == "GATE_LOOSENED")
    assert "90 → 40" in gate["items"][0]


def test_clean_change_has_no_tamper_flags(cart):
    write(cart, {"cart.py": CART_FEATURE, "test_cart.py": CART_TEST_V1 + STRONG_TEST})
    _, doc = check_json(cart, "--probes", "tamper")
    assert probe(doc, "tamper")["findings"] == []


# --- deps -------------------------------------------------------------------------------

def test_typosquat_npm_and_pypi(tmp_path):
    repo = make_repo(tmp_path, {"package.json": json.dumps({"dependencies": {"lodash": "^4"}}),
                                "requirements.txt": "requests\n"})
    write(repo, {"package.json": json.dumps({"dependencies": {"lodash": "^4", "lodahs": "1.0.0", "chalk": "5"}}),
                 "requirements.txt": "requests\nreqeusts==1.0\nnumpy\n"})
    _, doc = check_json(repo, "--probes", "deps")
    sq = next(f for f in probe(doc, "deps")["findings"] if f["code"] == "TYPOSQUAT_SUSPECT")
    joined = " ".join(sq["items"])
    assert "lodahs" in joined and "reqeusts" in joined
    assert "chalk" not in joined and "numpy" not in joined
    new = next(f for f in probe(doc, "deps")["findings"] if f["code"] == "NEW_DEPENDENCIES")
    assert len(new["items"]) == 4


def test_deps_manifest_parsers():
    assert deps.deps_from("pyproject.toml", b'[project]\ndependencies = ["Flask>=2", "pydantic_core"]\n') == {
        ("pypi", "flask"), ("pypi", "pydantic-core")}
    assert deps.deps_from("Cargo.toml", b'[dependencies]\nserde = "1"\nlocal = { path = "../x" }\n') == {
        ("crates", "serde")}
    assert ("go", "github.com/pkg/errors") in deps.deps_from("go.mod", b"require github.com/pkg/errors v0.9.1\n")
    assert deps.deps_from("package.json", b"{not json") == set()


def test_online_missing_package(tmp_path, monkeypatch):
    repo = make_repo(tmp_path, {"requirements.txt": "requests\n"})
    write(repo, {"requirements.txt": "requests\ntotally-made-up-pkg-xyz\n"})
    from bitecheck.config import Config
    from bitecheck.core import git as g
    from bitecheck.plan import make_plan
    monkeypatch.setattr(deps, "registry_info", lambda eco, name: {"exists": False, "created": None, "error": None})
    plan = make_plan(repo, "HEAD", None, Config())
    res = deps.run(plan, online=True)
    assert "DEPENDENCY_NOT_FOUND" in {f.code for f in res.findings}
    assert g  # imported for side effects only


# --- claims -----------------------------------------------------------------------------

@pytest.mark.parametrize("text,kinds", [
    ("All 12 tests pass.", {"tests_pass"}),
    ("I added comprehensive tests for the parser.", {"tests_added", "thorough"}),
    ("The tests don't pass yet.", set()),
    ("No tests were added because this is docs-only.", set()),
    ("This is a pure refactor; behaviour is unchanged.", {"no_behavior_change"}),
    ("I didn't modify any existing tests.", {"tests_untouched"}),
    ("Fixed the failing test, and now all tests pass.", {"tests_pass"}),
    ("```\n3 tests passed\n```\nI changed the parser.", set()),
    ("2 tests failed, so I stopped.", set()),
])
def test_claim_extraction(text, kinds):
    assert {c.kind for c in claims.extract(text)} == kinds


def test_claims_contradicted_end_to_end(cart):
    write(cart, {"cart.py": CART_FEATURE, "test_cart.py": CART_TEST_V1 + WEAK_TEST})
    msg = "Done. I didn't modify any existing tests, all tests pass, and the new code has comprehensive tests."
    proc, doc = check_json(cart, "--message", msg)
    cl = {c["kind"]: c["verdict"] for c in probe(doc, "claims")["claims"]}
    assert cl == {"tests_pass": "supported", "thorough": "contradicted", "tests_untouched": "contradicted"}
    assert proc.returncode == 1


def test_claims_from_claude_transcript(cart, tmp_path):
    write(cart, {"cart.py": CART_FEATURE})
    t = tmp_path / "t.jsonl"
    t.write_text(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text":
                 "I added tests and all tests pass."}]}}) + "\n")
    _, doc = check_json(cart, "--transcript", str(t))
    cl = {c["kind"]: c["verdict"] for c in probe(doc, "claims")["claims"]}
    assert cl["tests_added"] == "contradicted"  # no test file changed
    assert probe(doc, "claims")["agent"] == "claude"


def test_claims_autodiscovers_claude_session(cart):
    write(cart, {"cart.py": CART_FEATURE})
    home = cart.parent / "home"
    from bitecheck.transcripts import claude_slug
    d = home / ".claude" / "projects" / claude_slug(cart.resolve())
    d.mkdir(parents=True)
    (d / "s.jsonl").write_text(json.dumps({"type": "assistant", "message": {"content": [
        {"type": "text", "text": "All tests pass."}]}}) + "\n")
    proc = __import__("conftest").run_bc(cart, "--cmd", PYTEST, "--json", "--probes", "claims")
    doc = json.loads(proc.stdout)
    assert probe(doc, "claims")["claims"][0]["verdict"] == "supported"


def test_no_message_skips_claims(cart):
    write(cart, {"cart.py": CART_FEATURE})
    _, doc = check_json(cart, "--probes", "claims")
    assert probe(doc, "claims")["status"] == "skipped"
    assert git  # keep import
