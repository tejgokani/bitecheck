"""What changed: files, their roles, and the exact changed lines of code."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .config import Config
from .core import classify, git
from .lang import lexer


@dataclass
class Plan:
    repo: Path
    base: str
    head: str  # sha or git.WORKTREE
    changes: list[git.Change]
    test_changes: list[git.Change]
    code_changes: list[git.Change]
    harness_changes: list[git.Change]
    # path -> changed line numbers (HEAD numbering), only for mutable code files
    code_lines: dict[str, set[int]] = field(default_factory=dict)
    unsupported: list[str] = field(default_factory=list)  # code files we cannot mutate

    @property
    def head_label(self) -> str:
        return "working tree" if self.head == git.WORKTREE else self.head[:12]

    @property
    def changed_code_line_count(self) -> int:
        return sum(len(v) for v in self.code_lines.values())


def make_plan(repo: Path, base_ref: str, head_ref: str | None, cfg: Config) -> Plan:
    base = git.resolve_commit(repo, base_ref)
    head = git.WORKTREE if head_ref is None else git.resolve_commit(repo, head_ref)
    changes = git.changed_files(repo, base, head)
    tests, code, harness = [], [], []
    for ch in changes:
        if classify.is_test(ch.path, cfg.test_patterns):
            tests.append(ch)
        else:
            code.append(ch)
            if classify.is_harness(ch.path, cfg.harness_patterns):
                harness.append(ch)
    plan = Plan(repo, base, head, changes, tests, code, harness)
    for ch in code:
        if ch.status == "D" or classify.matches_any(ch.path, cfg.exclude):
            continue
        if lexer.spec_for(ch.path) is None:
            if ch not in harness:
                plan.unsupported.append(ch.path)
            continue
        lines = git.changed_lines(repo, base, head, ch.path, ch.status)
        if lines:
            plan.code_lines[ch.path] = lines
    return plan
