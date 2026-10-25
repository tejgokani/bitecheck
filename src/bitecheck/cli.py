"""Command-line interface."""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import tempfile
from pathlib import Path

from . import __version__, check, config, transcripts
from .core import git
from .core.runner import kill_all
from .plan import make_plan
from .report import feedback, jsonout, text

EXIT_OK, EXIT_FAIL, EXIT_USAGE, EXIT_HOOK_BLOCK, EXIT_INTERRUPTED = 0, 1, 2, 2, 130
COMMANDS = ("check", "plan", "hook", "install", "mcp", "explain")

DESCRIPTION = """\
bitecheck verifies a code change with execution evidence, not opinions.

It deliberately breaks the lines you (or your agent) changed and runs your
tests: every break no test notices is a changed line nothing checks. It also
runs the original tests against the new code, checks the agent's claims
against reality, and flags shortcuts like skipped tests and loosened gates.
Your repository is never modified.

commands: check (default) · plan · hook · install <agent> · mcp · explain <CODE>
"""

VALUE_OPTS = {"-C", "--base", "--head", "--cmd", "--mutant-cmd", "--check-cmd", "--junit", "--probes", "--skip",
              "--jobs", "--per-line", "--max-mutants", "--budget", "--min-score", "--timeout", "--message",
              "--message-file", "--transcript", "--html", "--sarif", "--markdown", "--link", "--max-rounds",
              "--test-pattern", "--exclude"}


def split_command(argv: list[str]) -> tuple[str, list[str]]:
    for i, tok in enumerate(argv):
        if tok == "--":
            break
        if tok in COMMANDS and (i == 0 or argv[i - 1] not in VALUE_OPTS):
            return tok, argv[:i] + argv[i + 1:]
    return "check", argv


def build_parser(command: str) -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="bitecheck" if command == "check" else f"bitecheck {command}",
                                 description=DESCRIPTION, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=f"bitecheck {__version__}")
    if command == "install":
        ap.add_argument("agent", choices=("claude", "codex", "gemini", "all"))
        ap.add_argument("-C", dest="directory", default=".")
        ap.add_argument("--global", dest="global_", action="store_true", help="install in your home config instead")
        ap.add_argument("--print", dest="print_only", action="store_true", help="print the config instead of writing")
        ap.add_argument("--uninstall", action="store_true")
        return ap
    if command == "explain":
        ap.add_argument("code", nargs="?")
        return ap
    if command == "mcp":
        return ap
    g = ap.add_argument_group("what to check")
    g.add_argument("-C", dest="directory", default=".", help="repository directory (default: .)")
    g.add_argument("--base", default="HEAD", help="base revision (default: HEAD)")
    g.add_argument("--head", default=None, help="head revision (default: working tree incl. untracked files)")
    g.add_argument("--test-pattern", action="append", default=[], metavar="GLOB", help="extra test-file glob")
    g.add_argument("--exclude", action="append", default=[], metavar="GLOB", help="never mutate these files")
    if command == "plan":
        g.add_argument("--cmd", default=None)
        return ap
    t = ap.add_argument_group("how to test")
    t.add_argument("--cmd", default=None, help="test command (auto-detected if omitted)")
    t.add_argument("--mutant-cmd", default=None, help="command for mutant runs (default: a fail-fast --cmd)")
    t.add_argument("--check-cmd", default=None, help="compile/type check that marks broken mutants as invalid")
    t.add_argument("--junit", default=None, metavar="PATH", help="JUnit XML your command writes (per-test detail)")
    t.add_argument("--timeout", type=float, default=None, help="seconds for one full-suite run (default 900)")
    t.add_argument("--link", action="append", default=None, metavar="DIR", help="dependency dir to symlink in")
    t.add_argument("--no-link", action="store_true")
    p = ap.add_argument_group("probes")
    p.add_argument("--probes", default=None, help="comma list: mutants,goalpost,claims,tamper,deps (default all)")
    p.add_argument("--skip", default=None, help="comma list of probes to skip")
    p.add_argument("--jobs", type=int, default=None, help="parallel mutant workers (default: auto)")
    p.add_argument("--per-line", type=int, default=None, help="mutants per changed line (default 1, 0 = all)")
    p.add_argument("--max-mutants", type=int, default=None, help="cap on mutants (default 80, 0 = no cap)")
    p.add_argument("--budget", type=float, default=None, help="seconds for the mutation phase (default unlimited)")
    p.add_argument("--min-score", type=float, default=None, help="gate on the share of changed lines checked (0-1)")
    p.add_argument("--online", action="store_true", help="let the deps probe query PyPI/npm/crates.io")
    c = ap.add_argument_group("agent claims")
    c.add_argument("--message", default=None, help="the agent's final message text")
    c.add_argument("--message-file", default=None, help="file containing the agent's final message")
    c.add_argument("--transcript", default=None, help="Claude Code / Codex session .jsonl to read the message from")
    c.add_argument("--no-transcript", action="store_true", help="don't auto-discover recent agent sessions")
    o = ap.add_argument_group("output")
    o.add_argument("--json", action="store_true", help="JSON on stdout")
    o.add_argument("--html", default=None, metavar="FILE", help="write a self-contained HTML report")
    o.add_argument("--sarif", default=None, metavar="FILE", help="write SARIF 2.1.0 (GitHub code scanning)")
    o.add_argument("--markdown", default=None, metavar="FILE", help="write a Markdown summary (PR comments)")
    o.add_argument("--feedback", action="store_true", help="print the agent-facing feedback instead of the report")
    o.add_argument("--strict", action="store_true", help="exit 1 on warnings too")
    o.add_argument("--keep", action="store_true", help="keep snapshots and logs")
    o.add_argument("-q", "--quiet", action="store_true")
    o.add_argument("-v", "--verbose", action="store_true")
    if command == "hook":
        ap.add_argument("--max-rounds", type=int, default=None, help="times to send the agent back (default 3)")
    return ap


def _sigterm(_s, _f):
    raise KeyboardInterrupt


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    command, rest = split_command(argv)
    args = build_parser(command).parse_args(rest)
    signal.signal(signal.SIGTERM, _sigterm)
    try:
        if command == "install":
            from .integrations import install
            return install.main(args)
        if command == "mcp":
            from .integrations import mcp
            return mcp.serve()
        if command == "explain":
            from .integrations import explain
            return explain.main(args.code)
        return _run(command, args)
    except KeyboardInterrupt:
        kill_all()
        print("bitecheck: interrupted; temporary snapshots removed", file=sys.stderr)
        return EXIT_INTERRUPTED
    except (git.GitError, config.ConfigError) as exc:
        print(f"bitecheck: error: {exc}", file=sys.stderr)
        return EXIT_USAGE


def build_config(args, repo: Path, base_sha: str) -> config.Config:
    cfg = config.load(repo, base_sha)
    if getattr(args, "cmd", None):
        cfg.test_cmd = args.cmd
    if not cfg.test_cmd:
        guess = config.detect_test_cmd(repo, base_sha)
        if guess:
            cfg.test_cmd, cfg.detected_cmd = guess, True
    cfg.test_patterns += args.test_pattern
    cfg.exclude += args.exclude
    if not hasattr(args, "probes"):
        return cfg
    for attr, key in (("mutant_cmd", "mutant_cmd"), ("check_cmd", "check_cmd")):
        if getattr(args, attr):
            setattr(cfg, key, getattr(args, attr))
    if args.junit is not None:
        cfg.junit = config.validate_relpath(args.junit, "junit")
    for attr in ("timeout", "jobs", "per_line", "max_mutants", "budget", "min_score"):
        v = getattr(args, attr)
        if v is not None:
            config.apply(cfg, {attr: v}, origin=f"--{attr.replace('_', '-')}")
    if getattr(args, "max_rounds", None) is not None:
        config.apply(cfg, {"max_rounds": args.max_rounds}, origin="--max-rounds")
    if args.no_link:
        cfg.link = []
    elif args.link is not None:
        cfg.link = [config.validate_relpath(x, "link") for x in args.link]
    if not cfg.mutant_cmd and cfg.test_cmd:
        cfg.mutant_cmd = config.fail_fast_variant(cfg.test_cmd)
    return cfg


def _probes(args, cfg: config.Config) -> list[str]:
    probes = list(cfg.probes)
    if args.probes:
        probes = [p.strip() for p in args.probes.split(",") if p.strip()]
    if args.skip:
        probes = [p for p in probes if p not in {s.strip() for s in args.skip.split(",")}]
    bad = set(probes) - set(config.ALL_PROBES)
    if bad:
        raise config.ConfigError(f"unknown probes: {', '.join(sorted(bad))}")
    return probes


def _read_hook_stdin() -> dict:
    if sys.stdin is None or sys.stdin.isatty():
        return {}
    try:
        raw = sys.stdin.read(5_000_000)
        data = json.loads(raw) if raw.strip() else {}
        return data if isinstance(data, dict) else {}
    except (ValueError, OSError):
        return {}


def _run(command: str, args) -> int:
    hook = command == "hook"
    hook_data = _read_hook_stdin() if hook else {}
    start = Path(args.directory)
    if hook and args.directory == "." and isinstance(hook_data.get("cwd"), str):
        start = Path(hook_data["cwd"])
    if not start.is_dir():
        raise config.ConfigError(f"not a directory: {start}")
    repo = git.repo_root(start)
    base_sha = git.resolve_commit(repo, args.base)
    cfg = build_config(args, repo, base_sha)
    plan = make_plan(repo, args.base, args.head, cfg)

    if command == "plan":
        print(_render_plan(plan, cfg))
        return EXIT_OK

    probes = _probes(args, cfg)
    message = _message(args, hook_data, repo, "claims" in probes)
    err = sys.stderr
    progress = None
    if not (args.quiet or args.json or hook or args.feedback):
        def progress(msg):
            print(f"bitecheck: {msg}", file=err, flush=True)
        if cfg.detected_cmd:
            progress(f"no test command configured; detected `{cfg.test_cmd}`")

    round_no, state_path = None, None
    if hook:
        if _already_verified(plan, cfg, probes):
            print("bitecheck: this exact change was already verified; nothing to do.", file=err)
            return EXIT_OK
        round_no, state_path = _hook_round(hook_data)
        if round_no > cfg.max_rounds:
            print(f"bitecheck: {cfg.max_rounds} verification round(s) already used this session; "
                  "letting the agent stop.", file=err)
            return EXIT_OK

    verdict, workdir = check.run(plan, cfg, probes=probes, message=message, online=args.online,
                                 keep=args.keep, progress=progress)

    if args.html:
        from .report import html
        Path(args.html).write_text(html.render(plan, verdict, cfg.test_cmd), encoding="utf-8")
    if args.sarif:
        from .report import sarif
        Path(args.sarif).write_text(sarif.render(plan, verdict), encoding="utf-8")
    if args.markdown:
        from .report import markdown
        Path(args.markdown).write_text(markdown.render(plan, verdict, cfg.test_cmd), encoding="utf-8")

    failed = verdict.failed(strict=args.strict)
    if hook:
        codes = {f.code for f in verdict.findings if f.severity == "error"}
        if codes and codes <= UNFIXABLE_BY_AGENT:
            # The agent cannot fix bitecheck's configuration; never trap it in a loop over that.
            _hook_log(hook_data, plan, verdict, round_no, False)
            print("bitecheck: not verifying: " + "; ".join(f.message for f in verdict.findings
                                                           if f.code in UNFIXABLE_BY_AGENT), file=err)
            return EXIT_OK
        _hook_log(hook_data, plan, verdict, round_no, failed)
        if failed:
            _save_round(state_path, round_no)
            print(feedback.render(plan, verdict, round_no, cfg.max_rounds), file=err)
            return EXIT_HOOK_BLOCK
        _clear_round(state_path)
        _save_verified(plan, cfg, probes)
        print(feedback.render(plan, verdict, blocking=False), file=err)
        return EXIT_OK
    if args.json:
        print(jsonout.render(plan, verdict, cfg.test_cmd))
    elif args.feedback:
        print(feedback.render(plan, verdict, blocking=failed))
    else:
        print(text.render(plan, verdict, cfg.test_cmd, sys.stdout, args.verbose, workdir))
    return EXIT_FAIL if failed else EXIT_OK


def _message(args, hook_data: dict, repo: Path, wanted: bool) -> transcripts.AgentMessage | None:
    if not wanted:
        return None
    if args.message:
        return transcripts.AgentMessage("unknown", args.message, "--message")
    if args.message_file:
        p = Path(args.message_file)
        try:
            return transcripts.AgentMessage("unknown", p.read_text(encoding="utf-8", errors="replace"), str(p))
        except OSError as exc:
            raise config.ConfigError(f"cannot read --message-file: {exc}") from exc
    if args.transcript:
        msg = transcripts.from_file(Path(args.transcript))
        if msg is None:
            raise config.ConfigError(f"no agent message found in {args.transcript}")
        return msg
    if hook_data:
        return transcripts.from_hook(hook_data)
    if args.no_transcript:
        return None
    return transcripts.latest_session(repo)


def _hook_log(data: dict, plan, verdict, round_no, blocked: bool) -> None:
    """Append one JSON line per hook run to $BITECHECK_HOOK_LOG (an audit trail)."""
    target = os.environ.get("BITECHECK_HOOK_LOG")
    if not target:
        return
    import time as _t
    rec = {"time": _t.strftime("%Y-%m-%dT%H:%M:%S%z"), "session_id": data.get("session_id"),
           "event": data.get("hook_event_name"), "repo": str(plan.repo), "round": round_no, "blocked": blocked,
           "verdict": verdict.worst, "score": verdict.score,
           "findings": sorted({f.code for f in verdict.findings if f.severity in ("error", "warn")})}
    try:
        with open(target, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec) + "\n")
    except OSError:
        pass


UNFIXABLE_BY_AGENT = {"NO_TEST_COMMAND"}


def _fingerprint(plan, cfg, probes) -> str:
    """Hash of everything that determines the verdict: the diff, untracked files, config and probes."""
    import hashlib
    h = hashlib.sha256()
    h.update(plan.base.encode())
    h.update(json.dumps([cfg.test_cmd, cfg.effective_mutant_cmd, cfg.min_score, cfg.per_line, sorted(probes)]).encode())
    args = ["diff", "--no-color", "--binary", plan.base] + ([] if plan.head == git.WORKTREE else [plan.head])
    h.update(git._git(plan.repo, *args))
    if plan.head == git.WORKTREE:
        for ch in plan.changes:
            if ch.status == "A":
                data = git.read_head_file(plan.repo, plan.head, ch.path)
                h.update(ch.path.encode() + b"\0" + (data or b""))
    return h.hexdigest()


def _verified_path(plan) -> Path:
    import hashlib
    return _state_dir() / f"verified-{hashlib.sha256(str(plan.repo).encode()).hexdigest()[:16]}"


def _already_verified(plan, cfg, probes) -> bool:
    if not plan.changes:
        return False
    try:
        return _verified_path(plan).read_text() == _fingerprint(plan, cfg, probes)
    except (OSError, git.GitError):
        return False


def _save_verified(plan, cfg, probes) -> None:
    if not plan.changes:
        return
    try:
        _verified_path(plan).write_text(_fingerprint(plan, cfg, probes))
    except (OSError, git.GitError):
        pass


def _state_dir() -> Path:
    d = Path(tempfile.gettempdir()) / f"bitecheck-hooks-{os.getuid()}"
    d.mkdir(mode=0o700, exist_ok=True)
    return d


def _hook_round(data: dict) -> tuple[int, Path | None]:
    sid = str(data.get("session_id") or "")
    safe = "".join(ch for ch in sid if ch.isalnum() or ch in "-_")[:80]
    if not safe:
        # No session id: fall back to the documented loop guard only.
        return (2 if data.get("stop_hook_active") else 1), None
    path = _state_dir() / f"{safe}.round"
    try:
        n = int(path.read_text()) if path.exists() else 0
    except (OSError, ValueError):
        n = 0
    if not data.get("stop_hook_active"):
        n = 0  # a fresh user turn starts a fresh budget
    return n + 1, path


def _save_round(path: Path | None, n: int | None) -> None:
    if path is not None and n is not None:
        try:
            path.write_text(str(n))
        except OSError:
            pass


def _clear_round(path: Path | None) -> None:
    if path is not None:
        path.unlink(missing_ok=True)


def _render_plan(plan, cfg) -> str:
    out = ["bitecheck plan", f"  base  {plan.base[:12]}", f"  head  {plan.head_label}",
           f"  tests {cfg.test_cmd or '(none detected)'}", ""]
    out.append(f"  code files ({len(plan.code_changes)}), {plan.changed_code_line_count} changed line(s) in mutable languages")
    for c in plan.code_changes:
        n = len(plan.code_lines.get(c.path, ()))
        tag = f"{n} line(s)" if c.path in plan.code_lines else ("unsupported" if c.path in plan.unsupported else "-")
        out.append(f"    {c.status} {c.path}  [{tag}]")
    out.append(f"  test files ({len(plan.test_changes)})")
    for c in plan.test_changes:
        out.append(f"    {c.status} {c.path}")
    if plan.harness_changes:
        out.append(f"  harness files ({len(plan.harness_changes)}): " + ", ".join(c.path for c in plan.harness_changes))
    return "\n".join(out)
