"""Temporary snapshots shared by probes. The user's repository is never written."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from .config import Config
from .core import git
from .plan import Plan


class Workspace:
    def __init__(self, plan: Plan, cfg: Config, keep: bool = False):
        self.plan = plan
        self.cfg = cfg
        self.keep = keep
        self.root = Path(tempfile.mkdtemp(prefix="bitecheck-"))
        self._base: Path | None = None
        self._head: Path | None = None

    def __enter__(self) -> Workspace:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        if not self.keep:
            shutil.rmtree(self.root, ignore_errors=True)

    @property
    def logs(self) -> Path:
        p = self.root / "logs"
        p.mkdir(exist_ok=True)
        return p

    def base(self) -> Path:
        if self._base is None:
            self._base = self.root / "base"
            git.materialize_commit(self.plan.repo, self.plan.base, self._base)
            self.prepare(self._base)
        return self._base

    def head(self) -> Path:
        if self._head is None:
            self._head = self.root / "head"
            if self.plan.head == git.WORKTREE:
                git.materialize_worktree(self.plan.repo, self._head)
            else:
                git.materialize_commit(self.plan.repo, self.plan.head, self._head)
            self.prepare(self._head)
        return self._head

    def copy(self, src: Path, name: str) -> Path:
        dst = self.root / name
        git.clone_tree(src, dst)
        return dst

    def prepare(self, tree: Path) -> None:
        if self.cfg.junit:
            git.remove_entry(tree, self.cfg.junit)  # never read a stale, committed report
        for name in self.cfg.link:
            rel = git.safe_relpath(name)
            src = self.plan.repo / rel
            dst = tree / rel
            if not src.exists() or os.path.lexists(dst):
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            os.symlink(src.resolve(), dst)
