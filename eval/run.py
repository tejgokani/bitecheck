#!/usr/bin/env python3
"""Controlled evaluation: does putting bitecheck in the agent loop produce better tests?

Arms (identical except for the hook):
  A  agent alone
  B  agent + `bitecheck hook` as a Claude Code Stop hook (max 3 rounds)

Primary metric is INDEPENDENT of bitecheck: every task ships a correct reference
implementation and 5 hand-written buggy implementations. The agent's final
test files are run against each; a good test suite passes on the reference and
fails on every bug ("held-out bugs caught"). Secondary: hidden correctness tests
on the agent's own implementation, and bitecheck's own mutation score.

usage:
  eval/run.py validate                     # check the benchmark itself
  eval/run.py run --tasks all --arms A,B --reps 1 --out eval/results/<name>
  eval/run.py score <workspace>            # rescore one finished workspace
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
TASKS = HERE / "tasks"
ROOT = HERE.parent
BITECHECK = ROOT / ".venv" / "bin" / "bitecheck"
GIT_ENV = {**os.environ, "GIT_AUTHOR_NAME": "eval", "GIT_AUTHOR_EMAIL": "eval@example.com",
           "GIT_COMMITTER_NAME": "eval", "GIT_COMMITTER_EMAIL": "eval@example.com"}
MODEL: str | None = None
PROMPT = ("Read TASK.md and implement the task. Run the tests with: {cmd}\n"
          "When you are done, briefly summarize what you did.")
ISSUE_PROMPT = ("Fix this bug report:\n\n{issue}\n\nRun the tests with: {cmd}\n"
                "When you are done, briefly summarize what you did.")
TEST_GLOBS = {"python": ["test_*.py", "*_test.py"], "js": ["*.test.mjs", "*.test.js"], "go": ["*_test.go"]}


def sh(cmd, cwd, timeout=600, env=None):
    return subprocess.run(cmd, cwd=cwd, shell=isinstance(cmd, str), capture_output=True, text=True,
                          timeout=timeout, env=env)


def meta(task: str) -> dict:
    return json.loads((TASKS / task / "meta.json").read_text())


def ext(m: dict) -> str:
    return Path(m["impl"]).suffix


def make_venv(ws: Path, m: dict) -> None:
    if m["lang"] == "python":
        sh(["uv", "venv", "-q", ".venv", "-p", "3.12"], ws)
        sh(["uv", "pip", "install", "-q", "-p", ".venv", "pytest"], ws, timeout=300)


def copy_tracked(src: Path, dst: Path) -> None:
    """Copy a workspace minus VCS/agent/venv dirs."""
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns(".git", ".claude", "__pycache__", ".pytest_cache"),
                    symlinks=True)


def run_tests(tree: Path, m: dict, only: list[str] | None = None, timeout=300) -> bool:
    cmd = m["cmd"]
    if only:
        if m["lang"] == "python":
            cmd = f"{cmd} {' '.join(only)}"
        elif m["lang"] == "js":
            cmd = f"node --test {' '.join(only)}"
        elif m["lang"] == "go":
            # go runs all _test.go files in the package: remove the others instead
            for p in tree.glob("*_test.go"):
                if p.name not in only:
                    p.unlink()
    try:
        return sh(cmd, tree, timeout=timeout).returncode == 0
    except subprocess.TimeoutExpired:
        return False


def test_outcomes(tree: Path, m: dict, only: list[str], timeout=300) -> dict[str, bool] | None:
    """Per-test pass/fail for the given test files, or None if the run produced no report."""
    import xml.etree.ElementTree as ET
    report = tree / "eval-report.xml"
    report.unlink(missing_ok=True)
    if m["lang"] == "python":
        cmd = f"{m['cmd']} {' '.join(only)} --junitxml={report}"
    elif m["lang"] == "js":
        cmd = f"node --test --test-reporter=junit --test-reporter-destination={report} {' '.join(only)}"
    else:
        for p in tree.glob("*_test.go"):
            if p.name not in only:
                p.unlink()
        cmd = "go test -json ./..."
    try:
        proc = sh(cmd, tree, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None
    out: dict[str, bool] = {}
    if m["lang"] == "go":
        for line in proc.stdout.splitlines():
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if d.get("Test") and d.get("Action") in ("pass", "fail"):
                out[d["Test"]] = d["Action"] == "pass"
        if not out and proc.returncode != 0:
            return {"<build>": False}
        return out or None
    if not report.exists():
        return None
    for case in ET.parse(report).getroot().iter("testcase"):
        tid = f"{case.get('classname', '')}::{case.get('name', '')}"
        failed = any(ch.tag in ("failure", "error") for ch in case)
        skipped = any(ch.tag == "skipped" for ch in case)
        if not skipped:
            out[tid] = not failed and out.get(tid, True)
    if not out and proc.returncode != 0:
        return {"<collection>": False}
    return out


def validate() -> int:
    ok = True
    for t in sorted(p.name for p in TASKS.iterdir() if p.is_dir()):
        m = meta(t)
        with tempfile.TemporaryDirectory() as d:
            ws = Path(d) / t
            shutil.copytree(TASKS / t / "task", ws)
            make_venv(ws, m)
            hidden = [p.name for p in (TASKS / t / "hidden").iterdir()]
            for h in hidden:
                shutil.copy(TASKS / t / "hidden" / h, ws / h)
            shutil.copy(TASKS / t / f"reference{ext(m)}", ws / m["impl"])
            ref_ok = run_tests(ws, m, hidden)
            caught = []
            for bug in sorted((TASKS / t / "bugs").iterdir()):
                shutil.copy(bug, ws / m["impl"])
                caught.append(not run_tests(ws, m, hidden))
            print(f"{t:<10} reference passes hidden tests: {ref_ok}   hidden tests catch bugs: {sum(caught)}/{len(caught)}")
            ok &= ref_ok and all(caught)
    print("benchmark valid" if ok else "BENCHMARK INVALID")
    return 0 if ok else 1


def prepare(task: str, arm: str, out: Path) -> Path:
    m = meta(task)
    ws = out / f"{task}-{arm}"
    if ws.exists():
        shutil.rmtree(ws)
    shutil.copytree(TASKS / task / "task", ws)
    (ws / ".gitignore").write_text(".venv/\n__pycache__/\n.pytest_cache/\n.claude/\nreport.xml\n")
    (ws / ".bitecheck.toml").write_text(f'test_cmd = "{m["cmd"]}"\nmax_mutants = 0\nmax_rounds = 3\n')
    sh(["git", "init", "-q", "-b", "main"], ws)
    sh(["git", "add", "-A"], ws)
    sh(["git", "commit", "-q", "-m", "task"], ws, env=GIT_ENV)
    make_venv(ws, m)
    if arm.startswith("B"):  # arm labels carry the repetition: "B0", "B1"
        (ws / ".claude").mkdir()
        hook = {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": f"{BITECHECK} hook", "timeout": 1800}]}]}}
        (ws / ".claude" / "settings.json").write_text(json.dumps(hook, indent=2))
    return ws


def run_agent(ws: Path, task: str, timeout: int = 1800) -> dict:
    m = meta(task)
    issue = TASKS / task / "ISSUE.md"
    prompt = ISSUE_PROMPT.format(issue=issue.read_text().strip(), cmd=m["cmd"]) if issue.exists() else \
        PROMPT.format(cmd=m["cmd"])
    tool_cmd = m["cmd"].split(" ./...")[0] if m["lang"] == "go" else m["cmd"].split(" -q")[0]
    allowed = ["Read", "Edit", "Write", "Glob", "Grep", f"Bash({tool_cmd}:*)", f"Bash({m['cmd']}:*)"]
    if m["lang"] == "go":
        allowed += ["Bash(go test:*)", "Bash(go vet:*)", "Bash(gofmt:*)"]
    if m["lang"] == "js":
        allowed += ["Bash(node:*)"]
    start = time.time()
    log = ws.parent / f"{ws.name}.agent.jsonl"
    with open(log, "w") as fh:
        try:
            model = ["--model", MODEL] if MODEL else []
            hook_log = ws.parent / f"{ws.name}.hooks.jsonl"
            env = {**os.environ, "BITECHECK_HOOK_LOG": str(hook_log)}
            proc = subprocess.run(["claude", "-p", prompt, *model, "--permission-mode", "acceptEdits", "--allowedTools", *allowed,
                                   "--output-format", "stream-json", "--verbose"], cwd=ws, stdout=fh,
                                  stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, timeout=timeout, env=env)
            code = proc.returncode
        except subprocess.TimeoutExpired:
            code = "timeout"
    result = {"exit": code, "seconds": round(time.time() - start, 1)}
    rounds, final = 0, ""
    for line in log.read_text(errors="replace").splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        s = json.dumps(d)
        rounds += s.count("bitecheck round ")
        if d.get("type") == "result":
            result["cost_usd"] = d.get("total_cost_usd")
            result["turns"] = d.get("num_turns")
            final = d.get("result") or ""
    hook_log = ws.parent / f"{ws.name}.hooks.jsonl"
    hooks = [json.loads(x) for x in hook_log.read_text().splitlines()] if hook_log.exists() else []
    result["hook_runs"] = len(hooks)
    result["hook_blocks"] = sum(1 for h in hooks if h.get("blocked"))
    result["hook_rounds"] = max(rounds, result["hook_blocks"])
    result["final_message"] = final[:1500]
    return result


def score(ws: Path, task: str) -> dict:
    m = meta(task)
    res: dict = {}
    # 1. hidden correctness of the agent's implementation
    with tempfile.TemporaryDirectory() as d:
        tree = Path(d) / "t"
        copy_tracked(ws, tree)
        hidden = [p.name for p in (TASKS / task / "hidden").iterdir()]
        for h in hidden:
            shutil.copy(TASKS / task / "hidden" / h, tree / h)
        res["impl_correct"] = run_tests(tree, m, hidden)
    # 2. held-out bugs vs the agent's tests, judged per test: a bug is caught when a
    #    test that PASSES on the correct reference FAILS on the buggy one. Agent tests
    #    that fail on the reference (out-of-spec expectations) are excluded, not fatal.
    hidden_names = {p.name for p in (TASKS / task / "hidden").iterdir()}
    tests = sorted({p.name for g in TEST_GLOBS[m["lang"]] for p in ws.glob(g)} - hidden_names) or m["tests"]
    res["agent_test_files"] = tests
    with tempfile.TemporaryDirectory() as d:
        tree = Path(d) / "t"
        copy_tracked(ws, tree)
        shutil.copy(TASKS / task / f"reference{ext(m)}", tree / m["impl"])
        ref = test_outcomes(tree, m, tests) or {}
        good = {t for t, ok in ref.items() if ok}
        res["agent_tests"] = len(ref)
        res["agent_tests_failing_on_reference"] = sorted(t for t, ok in ref.items() if not ok)
        res["tests_valid_on_reference"] = bool(ref) and len(good) == len(ref)
        caught = {}
        for bug in sorted((TASKS / task / "bugs").iterdir()):
            shutil.copy(bug, tree / m["impl"])
            outcome = test_outcomes(tree, m, tests) or {}
            # a test missing from the buggy run (crash during collection) counts as failing
            caught[bug.stem] = any(not outcome.get(t, False) for t in good)
        res["bugs_caught"] = caught
        res["bugs_caught_n"] = sum(caught.values())
        res["bugs_total"] = len(caught)
        if "1_original_bug" in caught:
            res["regression_protected"] = caught["1_original_bug"]
    # 3. bitecheck's own view (fresh, no hook)
    proc = sh([str(BITECHECK), "--json", "--no-transcript", "--probes", "mutants,goalpost,tamper",
               "--max-mutants", "0"], ws, timeout=1800)
    try:
        doc = json.loads(proc.stdout)
        res["bitecheck_score"] = doc["score"]
        res["bitecheck_verdict"] = doc["verdict"]
        mut = next(p for p in doc["probes"] if p["name"] == "mutants").get("mutation", {})
        res["mutants"] = len([x for x in mut.get("mutants", []) if x["status"] in ("killed", "survived", "timeout")])
        res["red_flags"] = sorted({f["code"] for p in doc["probes"] for f in p["findings"]
                                   if f["severity"] in ("warn", "error") and f["code"] != "LINES_UNCHECKED"})
    except (ValueError, StopIteration):
        res["bitecheck_error"] = (proc.stderr or proc.stdout)[-400:]
    # 4. size of the tests the agent wrote
    res["test_lines"] = sum(len((ws / t).read_text().splitlines()) for t in tests if (ws / t).exists())
    return res


def run_all(tasks: list[str], arms: list[str], reps: int, out: Path, parallel: int) -> None:
    out.mkdir(parents=True, exist_ok=True)
    jobs = [(t, a, r) for r in range(reps) for t in tasks for a in arms]

    def one(job):
        t, a, r = job
        ws = prepare(t, f"{a}{r}", out)
        print(f"[start] {ws.name}", flush=True)
        agent = run_agent(ws, t)
        sc = score(ws, t)
        rec = {"task": t, "arm": a, "rep": r, "model": MODEL or "default", "tasks": TASKS.name, **agent, **sc}
        (out / f"{ws.name}.json").write_text(json.dumps(rec, indent=2))
        print(f"[done]  {ws.name}: bugs {sc['bugs_caught_n']}/{sc.get('bugs_total', 5)} reg={sc.get('regression_protected')} valid={sc['tests_valid_on_reference']} "
              f"impl={sc['impl_correct']} bitecheck={sc.get('bitecheck_score')} rounds={agent['hook_rounds']} "
              f"{agent['seconds']}s", flush=True)
        return rec

    with ThreadPoolExecutor(max_workers=parallel) as ex:
        records = list(ex.map(one, jobs))
    (out / "results.json").write_text(json.dumps(records, indent=2))
    print(summarize(records))


def summarize(records: list[dict]) -> str:
    lines = ["| task | arm | held-out bugs caught | agent tests (failing on reference) | impl correct | bitecheck score | hook runs/blocks | time | cost |",
             "|---|---|---|---|---|---|---|---|---|"]
    for r in sorted(records, key=lambda r: (r["task"], r["arm"], r["rep"])):
        bs = r.get("bitecheck_score")
        lines.append(f"| {r['task']} | {r['arm']} | {r['bugs_caught_n']}/{r.get('bugs_total', 5)}"
                     f"{' (regression: ' + ('yes' if r['regression_protected'] else 'NO') + ')' if 'regression_protected' in r else ''} | {r.get('agent_tests', '?')} "
                     f"({len(r.get('agent_tests_failing_on_reference', []))}) | "
                     f"{r['impl_correct']} | {'-' if bs is None else f'{bs:.0%}'} | {r.get('hook_runs', '?')}/{r['hook_rounds']} | "
                     f"{r['seconds']:.0f}s | {'-' if r.get('cost_usd') is None else '$%.2f' % r['cost_usd']} |")
    for arm in sorted({r["arm"] for r in records}):
        rs = [r for r in records if r["arm"] == arm]
        caught = sum(r["bugs_caught_n"] for r in rs)
        total = sum(r.get("bugs_total", 5) for r in rs)
        reg = [r["regression_protected"] for r in rs if "regression_protected" in r]
        reg_s = f", regression-protected {sum(reg)}/{len(reg)}" if reg else ""
        lines.append(f"\narm {arm}: {caught}/{total} held-out bugs caught ({caught / total:.0%}), "
                     f"impl correct {sum(r['impl_correct'] for r in rs)}/{len(rs)}{reg_s}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate")
    v.add_argument("--tasks-dir", default=None)
    r = sub.add_parser("run")
    r.add_argument("--tasks", default="all")
    r.add_argument("--arms", default="A,B")
    r.add_argument("--reps", type=int, default=1)
    r.add_argument("--parallel", type=int, default=4)
    r.add_argument("--out", required=True)
    r.add_argument("--tasks-dir", default=None)
    r.add_argument("--model", default=None)
    s = sub.add_parser("score")
    s.add_argument("workspace")
    s.add_argument("task")
    s.add_argument("--tasks-dir", default=None)
    sm = sub.add_parser("summarize")
    sm.add_argument("results")
    a = ap.parse_args()
    global TASKS, MODEL
    if getattr(a, "tasks_dir", None):
        TASKS = Path(a.tasks_dir).resolve()
    MODEL = getattr(a, "model", None)
    if a.cmd == "validate":
        return validate()
    if a.cmd == "score":
        print(json.dumps(score(Path(a.workspace), a.task), indent=2))
        return 0
    if a.cmd == "summarize":
        print(summarize(json.loads(Path(a.results).read_text())))
        return 0
    tasks = sorted(p.name for p in TASKS.iterdir() if p.is_dir()) if a.tasks == "all" else a.tasks.split(",")
    run_all(tasks, a.arms.split(","), a.reps, Path(a.out), a.parallel)
    return 0


if __name__ == "__main__":
    sys.exit(main())
