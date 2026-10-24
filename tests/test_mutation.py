"""End-to-end mutation probe: real repos, real test runs, the real CLI."""

import os
import signal
import subprocess
import time

from conftest import (
    CART_FEATURE,
    CART_TEST_V1,
    PY,
    PYTEST,
    SRC,
    STRONG_TEST,
    WEAK_TEST,
    check_json,
    codes,
    git,
    make_repo,
    needs_go,
    needs_node,
    probe,
    run_bc,
    write,
)


def test_weak_tests_leave_survivors(cart):
    write(cart, {"cart.py": CART_FEATURE, "test_cart.py": CART_TEST_V1 + WEAK_TEST})
    proc, doc = check_json(cart)
    assert proc.returncode == 1
    m = probe(doc, "mutants")["mutation"]
    survivors = {(x["line"], x["operator"]) for x in m["mutants"] if x["status"] == "survived"}
    assert (7, "negate-condition") in survivors and (8, "swap-arithmetic") in survivors
    assert m["score"] < 0.8
    assert "LINES_UNCHECKED" in codes(doc)


def test_strong_tests_kill_everything(cart):
    write(cart, {"cart.py": CART_FEATURE, "test_cart.py": CART_TEST_V1 + STRONG_TEST})
    proc, doc = check_json(cart)
    m = probe(doc, "mutants")["mutation"]
    assert m["score"] == 1.0, [x for x in m["mutants"] if x["status"] == "survived"]
    assert proc.returncode == 0, doc["probes"]
    assert doc["verdict"] == "ok"


def test_only_changed_lines_are_mutated(cart):
    write(cart, {"cart.py": CART_FEATURE, "test_cart.py": CART_TEST_V1 + STRONG_TEST})
    _, doc = check_json(cart)
    lines = {x["line"] for x in probe(doc, "mutants")["mutation"]["mutants"]}
    assert lines and min(lines) >= 5  # lines 1-2 (subtotal) did not change


def test_repo_is_byte_identical_after_run(cart):
    write(cart, {"cart.py": CART_FEATURE, "test_cart.py": CART_TEST_V1 + WEAK_TEST})
    (cart / "crlf.py").write_bytes(b"x = 1\r\ny = 2\r\n")
    git(cart, "add", "cart.py")  # partially staged state must survive
    snap = {p: p.read_bytes() for p in cart.rglob("*") if p.is_file() and ".git" not in p.parts}
    mt = {p: p.stat().st_mtime_ns for p in snap}
    status = git(cart, "status", "--porcelain=v2", "--untracked-files=all", "--ignored")
    index = (cart / ".git" / "index").read_bytes()
    check_json(cart)
    assert {p: p.read_bytes() for p in snap} == snap
    assert {p: p.stat().st_mtime_ns for p in snap} == mt
    assert git(cart, "status", "--porcelain=v2", "--untracked-files=all", "--ignored") == status
    assert (cart / ".git" / "index").read_bytes() == index
    assert git(cart, "worktree", "list", "--porcelain").count("worktree ") == 1


def test_crlf_files_mutated_and_restored_exactly(tmp_path):
    src = "def f(a, b):\r\n    return a + b\r\n"
    repo = make_repo(tmp_path, {"m.py": "def f(a, b):\r\n    return a\r\n",
                                "test_m.py": "from m import f\n\ndef test_f():\n    assert f(1, 2) in (1, 3)\n"})
    (repo / "m.py").write_bytes(src.encode())
    _, doc = check_json(repo, "--per-line", "0")
    muts = probe(doc, "mutants")["mutation"]["mutants"]
    assert muts and all(m["status"] in ("killed", "survived") for m in muts)
    assert (repo / "m.py").read_bytes() == src.encode()


def test_infinite_loop_mutant_counts_as_killed(tmp_path):
    code = "def count(n):\n    i = 0\n    while i < n:\n        i += 1\n    return i\n"
    repo = make_repo(tmp_path, {"loop.py": "def count(n):\n    return n\n",
                                "test_loop.py": "from loop import count\n\ndef test_c():\n    assert count(3) == 3\n"})
    write(repo, {"loop.py": code, ".bitecheck.toml": ""})
    _, doc = check_json(repo, "--per-line", "0", "--probes", "mutants")
    statuses = {(m["line"], m["replacement"]): m["status"] for m in probe(doc, "mutants")["mutation"]["mutants"]}
    assert statuses.get((4, "-=")) == "timeout"
    assert probe(doc, "mutants")["mutation"]["score"] is not None


def test_baseline_failure_means_not_judged(cart):
    write(cart, {"cart.py": CART_FEATURE + "\nraise SystemExit(3)\n"})
    proc, doc = check_json(cart, "--probes", "mutants")
    assert proc.returncode == 1
    assert "MUTANTS_NOT_JUDGED" in codes(doc) and "HEAD_FAILS" in codes(doc)


def test_cap_and_budget(cart):
    write(cart, {"cart.py": CART_FEATURE, "test_cart.py": CART_TEST_V1 + WEAK_TEST})
    _, doc = check_json(cart, "--probes", "mutants", "--max-mutants", "2")
    m = probe(doc, "mutants")["mutation"]
    assert len(m["mutants"]) == 2 and m["truncated"] > 0
    assert "MUTANTS_CAPPED" in codes(doc)


def test_exclude_glob(cart):
    write(cart, {"cart.py": CART_FEATURE, "test_cart.py": CART_TEST_V1 + WEAK_TEST})
    _, doc = check_json(cart, "--probes", "mutants", "--exclude", "cart.py")
    assert "NOTHING_TO_MUTATE" in codes(doc)


def test_unsupported_language_is_reported(tmp_path):
    repo = make_repo(tmp_path, {"x.zig": "const a = 1;\n", "test_x.py": "def test_x():\n    assert True\n"})
    write(repo, {"x.zig": "const a = 2;\n"})
    _, doc = check_json(repo, "--probes", "mutants")
    assert "UNSUPPORTED_LANGUAGE" in codes(doc)


def test_sigint_kills_workers_and_cleans_up(cart, tmp_path):
    write(cart, {"cart.py": CART_FEATURE, "test_cart.py": CART_TEST_V1 + WEAK_TEST})
    tmp = tmp_path / "tmp"
    tmp.mkdir()
    pidfile = tmp_path / "pids"
    env = {**os.environ, "PYTHONPATH": str(SRC), "TMPDIR": str(tmp)}
    # The baseline must pass quickly; mutant runs then hang so we can interrupt them.
    cmd = f'if [ -n "$BITECHECK_MUTANT" ]; then echo $$ >> {pidfile}; exec sleep 60; fi; {PYTEST}'
    proc = subprocess.Popen([PY, "-m", "bitecheck", "-C", str(cart), "--cmd", cmd, "--probes", "mutants", "-q",
                             "--jobs", "2", "--no-transcript"], env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, start_new_session=True)
    deadline = time.time() + 60
    while time.time() < deadline and not (pidfile.exists() and len(pidfile.read_text().split()) >= 2):
        time.sleep(0.2)
    pids = [int(x) for x in pidfile.read_text().split()]
    proc.send_signal(signal.SIGINT)
    proc.wait(timeout=30)
    assert proc.returncode == 130
    time.sleep(0.5)
    for pid in pids:
        try:
            os.kill(pid, 0)
            raise AssertionError(f"worker {pid} still alive")
        except ProcessLookupError:
            pass
    assert [p for p in tmp.iterdir() if p.name.startswith("bitecheck-")] == []
    assert (cart / "cart.py").read_text() == CART_FEATURE


@needs_node
def test_javascript_node_test(tmp_path):
    repo = make_repo(tmp_path, {
        "price.mjs": "export function price(b) {\n  return b;\n}\n",
        "price.test.mjs": "import { test } from 'node:test';\nimport assert from 'node:assert/strict';\n"
                          "import { price } from './price.mjs';\ntest('p', () => assert.equal(price(10), 10));\n"})
    write(repo, {"price.mjs": "export function price(b, qty = 1) {\n  const t = b * qty;\n"
                              "  if (t > 100) {\n    return t - 5;\n  }\n  return t;\n}\n"})
    _, doc = check_json(repo, "--probes", "mutants", cmd="node --test")
    m = probe(doc, "mutants")["mutation"]
    by_line = {x["line"]: x["status"] for x in m["mutants"]}
    assert by_line[3] == "killed"  # negating the guard sends price(10) into the discount branch
    assert by_line[4] == "survived"  # but the discount itself is never checked
    assert by_line[6] == "killed"  # `return t` → `return undefined` breaks price(10) == 10


@needs_go
def test_go_with_invalid_mutants(tmp_path):
    repo = make_repo(tmp_path, {
        "go.mod": "module example.com/x\n\ngo 1.22\n",
        "x.go": "package x\n\nfunc Name(a string) string {\n\treturn a\n}\n",
        "x_test.go": "package x\n\nimport \"testing\"\n\nfunc TestName(t *testing.T) {\n"
                     "\tif Name(\"a\") != \"a\" {\n\t\tt.Fatal(\"x\")\n\t}\n}\n"})
    write(repo, {"x.go": "package x\n\nfunc Name(a string) string {\n\tsuffix := \"!\"\n\treturn a + suffix\n}\n",
                 "x_test.go": "package x\n\nimport \"testing\"\n\nfunc TestName(t *testing.T) {\n"
                              "\tif Name(\"a\") != \"a!\" {\n\t\tt.Fatal(\"x\")\n\t}\n}\n"})
    _, doc = check_json(repo, "--probes", "mutants", cmd="go test ./...")
    m = probe(doc, "mutants")["mutation"]
    assert {x["status"] for x in m["mutants"]} == {"invalid"}  # string - string does not compile
    assert m["score"] is None


def test_plan_command(cart):
    write(cart, {"cart.py": CART_FEATURE, "test_cart.py": CART_TEST_V1 + WEAK_TEST})
    proc = run_bc(cart, "plan", "--cmd", PYTEST)
    assert proc.returncode == 0
    assert "cart.py  [9 line(s)]" in proc.stdout and "test_cart.py" in proc.stdout
