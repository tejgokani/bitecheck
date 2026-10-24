"""Find the agent's final message: from hook input, a file, or local session logs.

Supported session stores (formats inspected 2026-10-25):
  Claude Code  ~/.claude/projects/<cwd with / and . as ->/<session>.jsonl
  Codex CLI    ~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl
  Gemini CLI   hook input only (prompt_response)
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

MAX_AGE_S = 6 * 3600
MAX_FILE = 200 * 1024 * 1024


@dataclass
class AgentMessage:
    agent: str  # claude | codex | gemini | unknown
    text: str
    source: str


def from_hook(data: dict) -> AgentMessage | None:
    """Extract the final message from a Stop/AfterAgent hook payload."""
    if not isinstance(data, dict):
        return None
    if isinstance(data.get("prompt_response"), str):
        return AgentMessage("gemini", data["prompt_response"], "hook:prompt_response")
    if isinstance(data.get("last_assistant_message"), str):
        agent = "codex" if "turn_id" in data else "claude"
        return AgentMessage(agent, data["last_assistant_message"], "hook:last_assistant_message")
    tp = data.get("transcript_path")
    if isinstance(tp, str) and tp:
        return from_file(Path(tp))
    return None


def from_file(path: Path) -> AgentMessage | None:
    try:
        if not path.is_file() or path.stat().st_size > MAX_FILE:
            return None
    except OSError:
        return None
    text = None
    agent = "unknown"
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(d, dict):
                    continue
                if d.get("type") == "assistant" and isinstance(d.get("message"), dict):
                    t = _claude_text(d["message"])
                    if t:
                        text, agent = t, "claude"
                elif d.get("type") == "event_msg" and isinstance(d.get("payload"), dict):
                    p = d["payload"]
                    if p.get("type") == "task_complete" and isinstance(p.get("last_agent_message"), str):
                        text, agent = p["last_agent_message"], "codex"
                    elif p.get("type") == "agent_message" and isinstance(p.get("message"), str):
                        text, agent = p["message"], "codex"
    except OSError:
        return None
    if text is None:
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        if path.suffix in (".md", ".txt") or not raw.lstrip().startswith(("{", "[")):
            return AgentMessage("unknown", raw, str(path))
        return None
    return AgentMessage(agent, text, str(path))


def _claude_text(msg: dict) -> str | None:
    content = msg.get("content")
    if isinstance(content, str):
        return content or None
    if isinstance(content, list):
        parts = [c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"]
        joined = "\n".join(p for p in parts if p)
        return joined or None
    return None


def claude_slug(cwd: Path) -> str:
    return re.sub(r"[/.]", "-", str(cwd))


def latest_session(repo: Path, now: float | None = None) -> AgentMessage | None:
    """Most recent Claude Code or Codex session for this repo, if recent."""
    now = now or time.time()
    home = Path(os.environ.get("BITECHECK_HOME") or Path.home())
    candidates: list[tuple[float, Path]] = []
    cdir = home / ".claude" / "projects" / claude_slug(repo.resolve())
    if cdir.is_dir():
        for p in cdir.glob("*.jsonl"):
            try:
                candidates.append((p.stat().st_mtime, p))
            except OSError:
                pass
    xdir = home / ".codex" / "sessions"
    if xdir.is_dir():
        recent = sorted(xdir.glob("*/*/*/rollout-*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)[:30]
        for p in recent:
            if _codex_cwd(p) == str(repo.resolve()):
                candidates.append((p.stat().st_mtime, p))
    candidates = [c for c in candidates if now - c[0] < MAX_AGE_S]
    for _, p in sorted(candidates, reverse=True):
        msg = from_file(p)
        if msg:
            return msg
    return None


def _codex_cwd(p: Path) -> str | None:
    try:
        with open(p, encoding="utf-8", errors="replace") as fh:
            first = json.loads(fh.readline())
        return first.get("payload", {}).get("cwd")
    except (OSError, ValueError, AttributeError):
        return None
