"""Run the test command in a snapshot with a timeout and process-group kill."""

from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class RunResult:
    variant: str
    exit_code: int | None  # None => timed out or could not start
    duration: float
    timed_out: bool = False
    error: str | None = None
    output_tail: str = ""
    log_path: str | None = None
    tests: dict[str, str] | None = None  # junit test id -> pass|fail|error|skip
    junit_error: str | None = None
    extra: dict = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


TAIL_BYTES = 4000

# Every live child process group, so an interrupt in the main thread can kill
# work that worker threads started.
_ACTIVE: set[subprocess.Popen] = set()
_ACTIVE_LOCK = threading.Lock()


def kill_all() -> None:
    with _ACTIVE_LOCK:
        procs = list(_ACTIVE)
    for p in procs:
        _kill_group(p)


def run_command(cmd: str, cwd: Path, variant: str, timeout: float, log_path: Path,
                extra_env: dict | None = None) -> RunResult:
    env = dict(os.environ)
    env["BITECHECK_VARIANT"] = variant
    env["BITECHECK_TREE"] = str(cwd)
    # Keep tools from writing caches back into the user's repo via env-configured paths.
    env.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    if extra_env:
        env.update(extra_env)
    start = time.monotonic()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "wb") as log:
        try:
            proc = subprocess.Popen(
                cmd,
                shell=True,
                cwd=cwd,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        except OSError as exc:
            return RunResult(variant, None, 0.0, error=f"could not start: {exc}", log_path=str(log_path))
        with _ACTIVE_LOCK:
            _ACTIVE.add(proc)
        timed_out = False
        try:
            code = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill_group(proc)
            code = None
        except KeyboardInterrupt:
            _kill_group(proc)
            raise
        finally:
            with _ACTIVE_LOCK:
                _ACTIVE.discard(proc)
    duration = time.monotonic() - start
    return RunResult(
        variant,
        code,
        duration,
        timed_out=timed_out,
        output_tail=_tail(log_path),
        log_path=str(log_path),
    )


def _kill_group(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass
    # The leader may be gone while grandchildren (test workers, servers) linger.
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    proc.wait()


def _tail(path: Path) -> str:
    try:
        size = path.stat().st_size
        with open(path, "rb") as fh:
            if size > TAIL_BYTES:
                fh.seek(size - TAIL_BYTES)
            return fh.read().decode("utf-8", errors="replace")
    except OSError:
        return ""
