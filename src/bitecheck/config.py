"""Configuration: CLI flags over `.bitecheck.toml` read from the BASE revision.

The config file is read from the base commit, never the working tree, so the
change being verified cannot loosen its own gate (`min_score = 0`) or swap
the test command for `true`. Editing it is reported by the tamper probe.
"""

from __future__ import annotations

import json
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .core import classify, git

CONFIG_NAME = ".bitecheck.toml"
DEFAULT_LINKS = ["node_modules", ".venv", "venv", "vendor/bundle"]
ALL_PROBES = ("mutants", "goalpost", "claims", "tamper", "deps")


class ConfigError(ValueError):
    pass


@dataclass
class Config:
    test_cmd: str = ""
    mutant_cmd: str = ""  # defaults to test_cmd; ideally a fail-fast variant
    check_cmd: str = ""  # optional compile/type check to classify invalid mutants
    junit: str | None = None
    timeout: float = 900.0  # seconds for a full-suite run
    mutant_timeout_factor: float = 3.0
    min_mutant_timeout: float = 10.0
    jobs: int = 0  # 0 = auto
    per_line: int = 2
    max_mutants: int = 80
    budget: float = 0.0  # seconds for the whole mutation phase; 0 = unlimited
    min_score: float = 0.8
    test_patterns: list[str] = field(default_factory=lambda: list(classify.DEFAULT_TEST_PATTERNS))
    harness_patterns: list[str] = field(default_factory=lambda: list(classify.DEFAULT_HARNESS_PATTERNS))
    exclude: list[str] = field(default_factory=list)
    link: list[str] = field(default_factory=lambda: list(DEFAULT_LINKS))
    probes: list[str] = field(default_factory=lambda: list(ALL_PROBES))
    max_rounds: int = 3
    source: str = "defaults"
    detected_cmd: bool = False

    @property
    def effective_mutant_cmd(self) -> str:
        return self.mutant_cmd or self.test_cmd

    @property
    def effective_jobs(self) -> int:
        if self.jobs > 0:
            return self.jobs
        return max(1, min(4, (os.cpu_count() or 2) // 2))


_STR = {"test_cmd", "mutant_cmd", "check_cmd", "junit"}
_FLOAT = {"timeout", "mutant_timeout_factor", "min_mutant_timeout", "budget", "min_score"}
_INT = {"jobs", "per_line", "max_mutants", "max_rounds"}
_LIST = {"test_patterns", "extra_test_patterns", "harness_patterns", "exclude", "link", "probes"}


def load(repo: Path, base_sha: str) -> Config:
    cfg = Config()
    blob = git.show_file(repo, base_sha, CONFIG_NAME)
    if blob is None:
        return cfg
    try:
        data = tomllib.loads(blob.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"{CONFIG_NAME} at base is not valid TOML: {exc}") from exc
    cfg.source = f"{CONFIG_NAME} @ {base_sha[:12]}"
    apply(cfg, data, origin=CONFIG_NAME)
    return cfg


def apply(cfg: Config, data: dict, origin: str = "config") -> None:
    unknown = set(data) - _STR - _FLOAT - _INT - _LIST
    if unknown:
        raise ConfigError(f"{origin}: unknown keys: {', '.join(sorted(unknown))}")
    for k, v in data.items():
        if k in _STR:
            if not isinstance(v, str) or not v.strip():
                raise ConfigError(f"{origin}: '{k}' must be a non-empty string")
            setattr(cfg, k, validate_relpath(v, k) if k == "junit" else v)
        elif k in _FLOAT:
            if isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0:
                raise ConfigError(f"{origin}: '{k}' must be a non-negative number")
            if k == "min_score" and v > 1:
                raise ConfigError(f"{origin}: 'min_score' is a fraction between 0 and 1")
            if k == "timeout" and v == 0:
                raise ConfigError(f"{origin}: 'timeout' must be positive")
            setattr(cfg, k, float(v))
        elif k in _INT:
            if isinstance(v, bool) or not isinstance(v, int) or v < 0:
                raise ConfigError(f"{origin}: '{k}' must be a non-negative integer")
            setattr(cfg, k, v)
        else:
            if not isinstance(v, list) or not all(isinstance(x, str) and x for x in v):
                raise ConfigError(f"{origin}: '{k}' must be a list of non-empty strings")
            if k == "extra_test_patterns":
                cfg.test_patterns = cfg.test_patterns + v
            elif k == "link":
                cfg.link = [validate_relpath(x, k) for x in v]
            elif k == "probes":
                bad = set(v) - set(ALL_PROBES)
                if bad:
                    raise ConfigError(f"{origin}: unknown probes: {', '.join(sorted(bad))}")
                cfg.probes = v
            else:
                setattr(cfg, k, v)


def validate_relpath(p: str, what: str) -> str:
    try:
        return git.safe_relpath(p)
    except git.GitError as exc:
        raise ConfigError(f"{what} path must be relative to the repo root: {p!r}") from exc


def detect_test_cmd(repo: Path, base_sha: str) -> str | None:
    """Guess a test command from files at the base revision."""
    pkg = git.show_file(repo, base_sha, "package.json")
    if pkg is not None:
        try:
            scripts = json.loads(pkg).get("scripts", {})
        except (ValueError, AttributeError):
            scripts = {}
        if isinstance(scripts, dict) and isinstance(scripts.get("test"), str):
            for lock, runner in (("pnpm-lock.yaml", "pnpm"), ("yarn.lock", "yarn"),
                                 ("bun.lockb", "bun"), ("bun.lock", "bun")):
                if git.show_file(repo, base_sha, lock) is not None:
                    return f"{runner} test"
            return "npm test"
    if git.show_file(repo, base_sha, "Cargo.toml") is not None:
        return "cargo test"
    if git.show_file(repo, base_sha, "go.mod") is not None:
        return "go test ./..."
    for marker in ("pytest.ini", "conftest.py", "pyproject.toml", "setup.py", "tox.ini", "setup.cfg"):
        if git.show_file(repo, base_sha, marker) is not None:
            for venv in (".venv", "venv"):
                if (repo / venv / "bin" / "python").exists():
                    return f"{venv}/bin/python -m pytest -q"
            return "python3 -m pytest -q"
    if git.show_file(repo, base_sha, "Gemfile") is not None:
        return "bundle exec rake test"
    return None


def fail_fast_variant(cmd: str) -> str:
    """A fail-fast version of common test commands, for mutant runs.

    Stopping at the first failure is what makes per-mutant runs cheap; it never
    changes whether a mutant is killed.
    """
    c = cmd.strip()
    if "pytest" in c and " -x" not in c and "--exitfirst" not in c and "--maxfail" not in c:
        return c + " -x"
    if c.startswith("go test") and "-failfast" not in c:
        return c.replace("go test", "go test -failfast", 1)
    if ("jest" in c or c in ("npm test", "pnpm test", "yarn test")) and "--bail" not in c:
        return c  # npm scripts may not be jest; leave untouched
    return c
