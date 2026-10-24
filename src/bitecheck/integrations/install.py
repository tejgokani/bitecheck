"""`bitecheck install claude|codex|gemini`: register the verification hook.

The hook contracts come from each agent's official docs, verified 2026-10-25:
  Claude Code  Stop hook in .claude/settings.json; exit 2 + stderr continues the agent
  Codex CLI    Stop hook in .codex/hooks.json; exit 2 + stderr continues the agent
  Gemini CLI   AfterAgent hook in .gemini/settings.json; exit 2 + stderr retries
Edits are merged into existing files, idempotent, backed up, and reversible
with --uninstall.
"""

from __future__ import annotations

import json
import shlex
import shutil
import sys
from pathlib import Path

from ..core import git

MARK = "bitecheck hook"


def hook_command() -> str:
    exe = shutil.which("bitecheck")
    if exe:
        return f"{shlex.quote(exe)} hook"
    return f"{shlex.quote(sys.executable)} -m bitecheck hook"


TARGETS = {
    # agent: (relative config path, event, timeout value, timeout unit note)
    "claude": (".claude/settings.json", "Stop", 1800),
    "codex": (".codex/hooks.json", "Stop", 1800),
    "gemini": (".gemini/settings.json", "AfterAgent", 1_800_000),  # milliseconds
}


def entry(agent: str, cmd: str) -> dict:
    _, _, timeout = TARGETS[agent]
    hook = {"type": "command", "command": cmd, "timeout": timeout}
    if agent == "gemini":
        hook["name"] = "bitecheck"
        hook["description"] = "verify the change with execution evidence before finishing"
        return {"matcher": "*", "hooks": [hook]}
    return {"hooks": [hook]}


def _has(entries: list, mark: str = MARK) -> bool:
    return any(mark in json.dumps(e) for e in entries)


def merge(doc: dict, agent: str, cmd: str) -> tuple[dict, bool]:
    _, event, _ = TARGETS[agent]
    hooks = doc.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError("existing 'hooks' is not an object")
    lst = hooks.setdefault(event, [])
    if not isinstance(lst, list):
        raise ValueError(f"existing hooks.{event} is not a list")
    if _has(lst):
        return doc, False
    lst.append(entry(agent, cmd))
    return doc, True


def unmerge(doc: dict, agent: str) -> tuple[dict, bool]:
    _, event, _ = TARGETS[agent]
    lst = doc.get("hooks", {}).get(event)
    if not isinstance(lst, list):
        return doc, False
    kept = [e for e in lst if MARK not in json.dumps(e)]
    if len(kept) == len(lst):
        return doc, False
    if kept:
        doc["hooks"][event] = kept
    else:
        del doc["hooks"][event]
        if not doc["hooks"]:
            del doc["hooks"]
    return doc, True


def main(args) -> int:
    agents = ["claude", "codex", "gemini"] if args.agent == "all" else [args.agent]
    if args.global_:
        root = Path.home()
    else:
        root = git.repo_root(Path(args.directory))
    cmd = hook_command()
    rc = 0
    for agent in agents:
        rel, event, _ = TARGETS[agent]
        path = root / rel
        if args.print_only:
            print(f"# {path}")
            print(json.dumps({"hooks": {event: [entry(agent, cmd)]}}, indent=2))
            continue
        try:
            doc = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
            if not isinstance(doc, dict):
                raise ValueError("top level is not an object")
        except (ValueError, OSError) as exc:
            print(f"bitecheck: cannot read {path}: {exc}; not modified", file=sys.stderr)
            rc = 2
            continue
        try:
            doc, changed = unmerge(doc, agent) if args.uninstall else merge(doc, agent, cmd)
        except ValueError as exc:
            print(f"bitecheck: {path}: {exc}; not modified", file=sys.stderr)
            rc = 2
            continue
        if not changed:
            print(f"{agent}: {'not installed' if args.uninstall else 'already installed'} ({path})")
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            shutil.copy2(path, path.with_name(path.name + ".bitecheck.bak"))
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)
        verb = "removed from" if args.uninstall else "installed in"
        print(f"{agent}: {event} hook {verb} {path}")
        if agent == "codex" and not args.uninstall:
            print("  note: Codex runs project hooks only after you trust them: run /hooks in Codex once.")
    if not args.print_only and not args.uninstall:
        print("\nThe agent will now be sent back with evidence when its change fails verification "
              "(at most max_rounds times per turn, default 3).")
    return rc
