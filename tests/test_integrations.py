"""Hooks for Claude Code / Codex / Gemini, installer, MCP server, reports, CLI errors."""

import json
import os
import subprocess

import pytest
from conftest import CART_FEATURE, CART_TEST_V1, PY, PYTEST, SRC, STRONG_TEST, WEAK_TEST, make_repo, run_bc, write

ENV = {"BITECHECK_TEST": "1"}


def hook(repo, payload: dict, *args):
    return run_bc(repo, "hook", "--cmd", PYTEST, "--jobs", "2", *args, stdin=json.dumps(payload), env=ENV)


@pytest.mark.parametrize("agent,payload", [
    ("claude", {"hook_event_name": "Stop", "stop_hook_active": False}),
    ("codex", {"hook_event_name": "Stop", "turn_id": "t1", "stop_hook_active": False,
               "last_assistant_message": "Added comprehensive tests; all tests pass."}),
    ("gemini", {"hook_event_name": "AfterAgent", "stop_hook_active": False, "prompt": "add totals",
                "prompt_response": "Added comprehensive tests; all tests pass."}),
])
def test_hook_blocks_with_feedback(cart, agent, payload):
    write(cart, {"cart.py": CART_FEATURE, "test_cart.py": CART_TEST_V1 + WEAK_TEST})
    payload = {**payload, "session_id": f"s-{agent}", "cwd": str(cart)}
    proc = hook(cart, payload)
    assert proc.returncode == 2, proc.stderr
    assert proc.stdout == ""  # Codex/Gemini parse stdout as JSON: never print plain text there
    assert "Your tests do not check" in proc.stderr and "cart.py:" in proc.stderr
    assert "round 1 of 3" in proc.stderr
    if agent != "claude":
        assert "CLAIM_CONTRADICTED" in proc.stderr


def test_hook_round_limit_prevents_loops(cart):
    write(cart, {"cart.py": CART_FEATURE, "test_cart.py": CART_TEST_V1 + WEAK_TEST})
    base = {"hook_event_name": "Stop", "session_id": "loop-1", "cwd": str(cart)}
    assert hook(cart, {**base, "stop_hook_active": False}, "--max-rounds", "2").returncode == 2
    assert hook(cart, {**base, "stop_hook_active": True}, "--max-rounds", "2").returncode == 2
    third = hook(cart, {**base, "stop_hook_active": True}, "--max-rounds", "2")
    assert third.returncode == 0 and "letting the agent stop" in third.stderr
    # A new user turn (stop_hook_active false) gets a fresh budget.
    assert hook(cart, {**base, "stop_hook_active": False}, "--max-rounds", "2").returncode == 2


def test_hook_passes_good_change(cart):
    write(cart, {"cart.py": CART_FEATURE, "test_cart.py": CART_TEST_V1 + STRONG_TEST})
    proc = hook(cart, {"hook_event_name": "Stop", "session_id": "ok-1", "cwd": str(cart), "stop_hook_active": False})
    assert proc.returncode == 0, proc.stderr
    assert "verified" in proc.stderr


def test_hook_garbage_stdin(cart):
    write(cart, {"cart.py": CART_FEATURE, "test_cart.py": CART_TEST_V1 + STRONG_TEST})
    proc = run_bc(cart, "hook", "--cmd", PYTEST, stdin="not json at all", env=ENV)
    assert proc.returncode == 0 and "Traceback" not in proc.stderr


# --- installer ---------------------------------------------------------------------------

def install(repo, *args):
    env = {**os.environ, "PYTHONPATH": str(SRC)}
    return subprocess.run([PY, "-m", "bitecheck", "install", *args, "-C", str(repo)], capture_output=True,
                          text=True, env=env)


def test_install_all_agents_idempotent_and_reversible(tmp_path):
    repo = make_repo(tmp_path, {"a.py": "x = 1\n"})
    (repo / ".claude").mkdir()
    (repo / ".claude" / "settings.json").write_text(json.dumps({"model": "opus", "hooks": {"Stop": [
        {"hooks": [{"type": "command", "command": "echo mine"}]}]}}))
    assert install(repo, "all").returncode == 0
    claude = json.loads((repo / ".claude" / "settings.json").read_text())
    assert claude["model"] == "opus" and len(claude["hooks"]["Stop"]) == 2
    assert "bitecheck" in json.dumps(claude["hooks"]["Stop"][1]) and claude["hooks"]["Stop"][1]["hooks"][0]["timeout"] == 1800
    assert (repo / ".claude" / "settings.json.bitecheck.bak").exists()
    codex = json.loads((repo / ".codex" / "hooks.json").read_text())
    assert codex["hooks"]["Stop"][0]["hooks"][0]["command"].endswith("hook")
    gem = json.loads((repo / ".gemini" / "settings.json").read_text())
    assert gem["hooks"]["AfterAgent"][0]["matcher"] == "*"
    assert gem["hooks"]["AfterAgent"][0]["hooks"][0]["timeout"] == 1_800_000
    again = install(repo, "all")
    assert "already installed" in again.stdout
    assert len(json.loads((repo / ".claude" / "settings.json").read_text())["hooks"]["Stop"]) == 2
    assert install(repo, "all", "--uninstall").returncode == 0
    claude = json.loads((repo / ".claude" / "settings.json").read_text())
    assert claude["hooks"]["Stop"] == [{"hooks": [{"type": "command", "command": "echo mine"}]}]
    assert "hooks" not in json.loads((repo / ".codex" / "hooks.json").read_text())


def test_install_refuses_broken_json(tmp_path):
    repo = make_repo(tmp_path, {"a.py": "x = 1\n"})
    (repo / ".claude").mkdir()
    (repo / ".claude" / "settings.json").write_text("{broken")
    proc = install(repo, "claude")
    assert proc.returncode == 2 and (repo / ".claude" / "settings.json").read_text() == "{broken"


def test_install_print_only_writes_nothing(tmp_path):
    repo = make_repo(tmp_path, {"a.py": "x = 1\n"})
    proc = install(repo, "gemini", "--print")
    assert '"AfterAgent"' in proc.stdout and not (repo / ".gemini").exists()


# --- MCP ---------------------------------------------------------------------------------

def test_mcp_server(cart):
    write(cart, {"cart.py": CART_FEATURE, "test_cart.py": CART_TEST_V1 + WEAK_TEST})
    msgs = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "bitecheck_verify", "arguments": {
            "path": str(cart), "cmd": PYTEST, "probes": "mutants,tamper"}}},
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "nope"}},
        {"jsonrpc": "2.0", "id": 5, "method": "bogus"},
    ]
    env = {**os.environ, "PYTHONPATH": str(SRC)}
    proc = subprocess.run([PY, "-m", "bitecheck", "mcp"], input="\n".join(json.dumps(m) for m in msgs) + "\nnot json\n",
                          capture_output=True, text=True, env=env, timeout=300)
    out = [json.loads(line) for line in proc.stdout.splitlines()]
    by_id = {m.get("id"): m for m in out}
    assert by_id[1]["result"]["serverInfo"]["name"] == "bitecheck"
    assert {t["name"] for t in by_id[2]["result"]["tools"]} == {"bitecheck_verify", "bitecheck_plan"}
    text = by_id[3]["result"]["content"][0]["text"]
    assert "Your tests do not check" in text
    assert by_id[4]["error"]["code"] == -32602 and by_id[5]["error"]["code"] == -32601
    assert any(m.get("error", {}).get("code") == -32700 for m in out)


# --- reports & CLI ------------------------------------------------------------------------

def test_reports_written(cart, tmp_path):
    write(cart, {"cart.py": CART_FEATURE, "test_cart.py": CART_TEST_V1 + WEAK_TEST,
                 "<script>x.py": "alert = 1\n"})
    h, s, m = tmp_path / "r.html", tmp_path / "r.sarif", tmp_path / "r.md"
    run_bc(cart, "--cmd", PYTEST, "-q", "--no-transcript", "--html", str(h), "--sarif", str(s), "--markdown", str(m))
    html = h.read_text()
    assert "<script>x.py" not in html and "&lt;script&gt;x.py" in html  # escaped
    assert "src=\"http" not in html and "href=\"http" not in html and "@import" not in html  # self-contained
    sarif = json.loads(s.read_text())
    assert sarif["version"] == "2.1.0"
    res = sarif["runs"][0]["results"]
    assert res and all({"ruleId", "level", "message"} <= set(r) for r in res)
    assert any(r["ruleId"] == "unchecked-line" for r in res)
    rule_ids = {r["id"] for r in sarif["runs"][0]["tool"]["driver"]["rules"]}
    assert {r["ruleId"] for r in res} <= rule_ids
    md = m.read_text()
    assert md.startswith("## ❌ bitecheck: FAIL") and "| `cart.py:" in md


@pytest.mark.parametrize("args,needle", [
    (["--base", "nope"], "cannot resolve"),
    (["--probes", "mutants,unicorns"], "unknown probes"),
    (["--min-score", "1.5"], "fraction"),
    (["--junit", "../x.xml"], "relative"),
])
def test_cli_usage_errors(cart, args, needle):
    proc = run_bc(cart, "--cmd", PYTEST, *args)
    assert proc.returncode == 2 and needle in proc.stderr and "Traceback" not in proc.stderr


def test_not_a_repo(tmp_path):
    proc = run_bc(tmp_path, "--cmd", "true")
    assert proc.returncode == 2 and "Traceback" not in proc.stderr


def test_bad_config_at_base(tmp_path):
    repo = make_repo(tmp_path, {".bitecheck.toml": "test_cmd = [", "a.py": "x = 1\n"})
    proc = run_bc(repo, "--cmd", "true")
    assert proc.returncode == 2 and "not valid TOML" in proc.stderr


def test_config_read_from_base_not_head(cart):
    write(cart, {".bitecheck.toml": "min_score = 0.9\n"})
    from conftest import git
    git(cart, "add", "-A")
    git(cart, "commit", "-qm", "cfg")
    write(cart, {"cart.py": CART_FEATURE, "test_cart.py": CART_TEST_V1 + WEAK_TEST, ".bitecheck.toml": "min_score = 0\n"})
    proc = run_bc(cart, "--cmd", PYTEST, "--json", "--no-transcript")
    doc = json.loads(proc.stdout)
    assert doc["min_score"] == 0.9 and proc.returncode == 1


def test_explain_and_version():
    env = {**os.environ, "PYTHONPATH": str(SRC)}
    assert "What to do" in subprocess.run([PY, "-m", "bitecheck", "explain", "lines_unchecked"], capture_output=True,
                                          text=True, env=env).stdout
    assert subprocess.run([PY, "-m", "bitecheck", "--version"], capture_output=True, text=True,
                          env=env).stdout.startswith("bitecheck ")


def test_no_changes(cart):
    proc = run_bc(cart, "--cmd", PYTEST, "--json", "--no-transcript")
    assert proc.returncode == 0 and json.loads(proc.stdout)["verdict"] == "ok"


def test_hook_skips_already_verified_change(cart, tmp_path):
    write(cart, {"cart.py": CART_FEATURE, "test_cart.py": CART_TEST_V1 + STRONG_TEST})
    log = tmp_path / "hooks.jsonl"
    payload = {"hook_event_name": "Stop", "session_id": "cache-1", "cwd": str(cart), "stop_hook_active": False}
    env = {**ENV, "BITECHECK_HOOK_LOG": str(log)}
    first = run_bc(cart, "hook", "--cmd", PYTEST, stdin=json.dumps(payload), env=env)
    assert first.returncode == 0 and len(log.read_text().splitlines()) == 1
    second = run_bc(cart, "hook", "--cmd", PYTEST, stdin=json.dumps(payload), env=env)
    assert second.returncode == 0 and "already verified" in second.stderr
    assert len(log.read_text().splitlines()) == 1  # no second verification
    write(cart, {"cart.py": CART_FEATURE + "\n"})  # any change invalidates the cache
    third = run_bc(cart, "hook", "--cmd", PYTEST, stdin=json.dumps(payload), env=env)
    assert "already verified" not in third.stderr and len(log.read_text().splitlines()) == 2


def test_hook_never_blocks_on_missing_test_command(tmp_path):
    repo = make_repo(tmp_path, {"notes.txt": "a\n", "lib.py": "x = 1\n"})
    write(repo, {"lib.py": "x = 2\n"})
    proc = run_bc(repo, "hook", stdin=json.dumps({"hook_event_name": "Stop", "session_id": "nt", "cwd": str(repo)}),
                  env=ENV)
    assert proc.returncode == 0 and "not verifying" in proc.stderr


def test_non_blocking_feedback_header(cart):
    write(cart, {"cart.py": CART_FEATURE, "test_cart.py": CART_TEST_V1 + STRONG_TEST + "\n\ndef test_skip():\n"
                 "    import pytest\n    pytest.skip('later')\n"})
    proc = run_bc(cart, "--cmd", PYTEST, "--feedback", "--no-transcript")
    assert proc.returncode == 0 and "do not block" in proc.stdout and "not done yet" not in proc.stdout
