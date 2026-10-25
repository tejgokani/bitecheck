"""The mutation probe: do the tests notice when the *changed* code is wrong?

For every changed line of code, bitecheck applies the strongest applicable
mutant, runs your test command in an isolated copy-on-write worker tree, and
records whether any test failed. A surviving mutant is a changed line whose
behaviour no test checks.
"""

from __future__ import annotations

import queue
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..config import Config
from ..core import junit
from ..core.runner import RunResult, run_command
from ..lang import lexer, mutators
from ..plan import Plan
from ..workspace import Workspace

KILLED, SURVIVED, TIMEOUT, INVALID, SKIPPED = "killed", "survived", "timeout", "invalid", "skipped"

# Output signatures that mean "the mutant did not compile/parse", which says
# nothing about the tests. Kept specific to avoid hiding real kills.
_INVALID_SIGS = re.compile(
    r"(error\[E\d{4}\]|could not compile|error TS\d{4}|\.go:\d+:\d+: (?:syntax error|cannot use|invalid operation|"
    r"mismatched types|undefined:|.* declared and not used)|\[build failed\]|\.java:\d+: error:|COMPILATION ERROR|"
    r"error CS\d{4}|\.(?:c|cc|cpp|cxx|h|hpp):\d+:\d+: error:|\.swift:\d+:\d+: error:|^e: .*\.kt|"
    r"PHP Parse error|Parse error: syntax error|SyntaxError: (?:Unexpected|Invalid|missing)|syntax error, unexpected)",
    re.M,
)


@dataclass
class MutantResult:
    mutant: mutators.Mutant
    status: str
    duration: float = 0.0
    killed_by: list[str] = field(default_factory=list)
    note: str = ""


@dataclass
class FileStats:
    path: str
    changed_lines: int
    mutated_lines: int = 0
    killed: int = 0
    survived: int = 0
    timeout: int = 0
    invalid: int = 0
    skipped: int = 0


@dataclass
class MutationReport:
    baseline: RunResult | None
    results: list[MutantResult]
    files: dict[str, FileStats]
    cmd: str
    jobs: int
    clone_method: str = ""
    error: str | None = None  # set when the probe could not run at all
    truncated: int = 0  # mutants dropped by max_mutants
    elapsed: float = 0.0
    unloaded: dict[str, str] = field(default_factory=dict)  # files whose canary survived

    @property
    def counted(self) -> list[MutantResult]:
        return [r for r in self.results if r.status in (KILLED, SURVIVED, TIMEOUT)]

    @property
    def score(self) -> float | None:
        c = self.counted
        if not c:
            return None
        return sum(1 for r in c if r.status != SURVIVED) / len(c)

    @property
    def survivors(self) -> list[MutantResult]:
        return [r for r in self.results if r.status == SURVIVED]


def plan_mutants(plan: Plan, cfg: Config, tree: Path) -> tuple[list[mutators.Mutant], dict[str, FileStats], int]:
    all_m: list[mutators.Mutant] = []
    stats: dict[str, FileStats] = {}
    for path, lines in sorted(plan.code_lines.items()):
        spec = lexer.spec_for(path)
        fpath = tree / path
        if spec is None or not fpath.is_file():
            continue
        try:
            text = read_text(fpath)
        except (UnicodeDecodeError, OSError):
            continue
        ms = mutators.select(mutators.generate(path, text, spec, lines), cfg.per_line)
        stats[path] = FileStats(path, len(lines), mutated_lines=len({m.line for m in ms}))
        all_m += ms
    truncated = 0
    if cfg.max_mutants and len(all_m) > cfg.max_mutants:
        # Spread the budget across files and lines instead of taking the first N.
        step = len(all_m) / cfg.max_mutants
        keep = [all_m[int(i * step)] for i in range(cfg.max_mutants)]
        truncated = len(all_m) - len(keep)
        all_m = keep
        for st in stats.values():
            st.mutated_lines = len({m.line for m in all_m if m.path == st.path})
    return all_m, stats, truncated


def run(plan: Plan, cfg: Config, ws: Workspace, progress=None, baseline: RunResult | None = None) -> MutationReport:
    say = progress or (lambda msg: None)
    cmd = cfg.effective_mutant_cmd
    start = time.monotonic()
    head = ws.head()
    mutants, stats, truncated = plan_mutants(plan, cfg, head)
    report = MutationReport(None, [], stats, cmd, cfg.effective_jobs, truncated=truncated)
    if not mutants:
        report.elapsed = time.monotonic() - start
        return report

    if baseline is None:
        say(f"mutants: baseline run of `{cmd}`")
        baseline = run_command(cmd, head, "mutants-baseline", cfg.timeout, ws.logs / "mutants-baseline.log")
    report.baseline = baseline
    if not baseline.passed:
        report.error = ("the test command does not pass on the change itself, so mutants cannot be judged"
                        if not baseline.timed_out else "the baseline test run timed out")
        report.results = [MutantResult(m, SKIPPED, note="baseline failed") for m in mutants]
        report.elapsed = time.monotonic() - start
        _tally(report)
        return report

    per_timeout = max(cfg.min_mutant_timeout, baseline.duration * cfg.mutant_timeout_factor + 5.0)

    # Canary: break each mutated file outright. If the suite still passes, no test
    # loads this copy of the file (untested file, or an editable install / absolute
    # path importing the user's checkout), so its mutants cannot be judged.
    dead_files: dict[str, str] = {}
    for path in sorted({m.path for m in mutants}):
        say(f"mutants: canary run for {path}")
        if not _canary_killed(head, path, cmd, per_timeout, ws.logs / "canary.log"):
            dead_files[path] = "the test suite still passes with this file deliberately broken: no test loads it"
    if dead_files:
        report.unloaded = dead_files
        skipped = [m for m in mutants if m.path in dead_files]
        mutants = [m for m in mutants if m.path not in dead_files]
        report.results += [MutantResult(m, SKIPPED, note="file not loaded by any test") for m in skipped]
        if not mutants:
            report.elapsed = time.monotonic() - start
            _tally(report)
            return report
    jobs = max(1, min(cfg.effective_jobs, len(mutants)))
    report.jobs = jobs
    trees = []
    for i in range(jobs):
        trees.append(ws.copy(head, f"worker{i}"))
    report.clone_method = "clone" if trees else ""
    say(f"mutants: {len(mutants)} mutant(s) on {sum(s.mutated_lines for s in stats.values())} changed line(s), "
        f"{jobs} worker(s), {per_timeout:.0f}s timeout each")

    work: queue.Queue = queue.Queue()
    for m in mutants:
        work.put(m)
    results: dict[str, MutantResult] = {}
    lock = threading.Lock()
    stop = threading.Event()
    deadline = start + cfg.budget if cfg.budget else None
    done_count = [0]

    def worker(idx: int, tree: Path) -> None:
        while not stop.is_set():
            try:
                m = work.get_nowait()
            except queue.Empty:
                return
            if deadline and time.monotonic() > deadline:
                res = MutantResult(m, SKIPPED, note="time budget exhausted")
            else:
                res = _run_one(m, tree, cfg, cmd, per_timeout, ws.logs / f"w{idx}.log")
            with lock:
                results[m.id] = res
                done_count[0] += 1
                n = done_count[0]
            mark = {KILLED: "killed", SURVIVED: "SURVIVED", TIMEOUT: "timeout", INVALID: "invalid",
                    SKIPPED: "skipped"}[res.status]
            say(f"  [{n}/{len(mutants)}] {m.path}:{m.line} {m.describe()} → {mark}")

    threads = [threading.Thread(target=worker, args=(i, t), daemon=True) for i, t in enumerate(trees)]
    for t in threads:
        t.start()
    try:
        for t in threads:
            while t.is_alive():
                t.join(0.2)
    except KeyboardInterrupt:
        stop.set()
        from ..core.runner import kill_all
        kill_all()
        raise
    report.results += [results.get(m.id) or MutantResult(m, SKIPPED) for m in mutants]
    report.elapsed = time.monotonic() - start
    _tally(report)
    return report


def _run_one(m: mutators.Mutant, tree: Path, cfg: Config, cmd: str, timeout: float, log: Path) -> MutantResult:
    fpath = tree / m.path
    original = read_text(fpath)
    mutated = m.apply(original)
    if m.path.endswith((".py", ".pyi")):
        try:
            compile(mutated, m.path, "exec")
        except (SyntaxError, ValueError) as exc:
            return MutantResult(m, INVALID, note=f"does not compile: {exc.__class__.__name__}")
    try:
        write_text(fpath, mutated)
        if cfg.check_cmd:
            chk = run_command(cfg.check_cmd, tree, "mutant-check", timeout, log)
            if not chk.passed:
                return MutantResult(m, INVALID, chk.duration, note="check_cmd failed")
        if cfg.junit:
            (tree / cfg.junit).unlink(missing_ok=True)
        res = run_command(cmd, tree, "mutant", timeout, log, extra_env={"BITECHECK_MUTANT": m.id})
        if res.timed_out:
            return MutantResult(m, TIMEOUT, res.duration, note="test run hung: counted as killed")
        if res.exit_code is None:
            return MutantResult(m, INVALID, res.duration, note=res.error or "could not run")
        if res.passed:
            return MutantResult(m, SURVIVED, res.duration)
        if _INVALID_SIGS.search(res.output_tail):
            return MutantResult(m, INVALID, res.duration, note="compile/parse error")
        killed_by: list[str] = []
        if cfg.junit:
            try:
                killed_by = sorted(t for t, o in junit.parse(tree / cfg.junit).items() if o in ("fail", "error"))
            except junit.JUnitError:
                pass
        return MutantResult(m, KILLED, res.duration, killed_by=killed_by[:5])
    finally:
        write_text(fpath, original)


_CANARY = {
    "python": "raise SystemExit('bitecheck canary: this file was deliberately broken')\n",
    "ruby": "raise 'bitecheck canary'\n",
}


def _canary_killed(tree: Path, path: str, cmd: str, timeout: float, log: Path) -> bool:
    """True if breaking `path` makes the test command fail (i.e. tests load it)."""
    spec = lexer.spec_for(path)
    fpath = tree / path
    original = read_text(fpath)
    if spec is not None and spec.family in _CANARY:
        broken = _CANARY[spec.family] + original
    else:
        # A line no C-family parser accepts, at the top of the file.
        broken = "@@@ bitecheck canary: deliberately broken @@@ ((\n" + original
    try:
        write_text(fpath, broken)
        res = run_command(cmd, tree, "canary", timeout, log)
        return not res.passed
    finally:
        write_text(fpath, original)


def read_text(p: Path) -> str:
    # newline="" keeps CRLF files byte-identical when restored.
    with open(p, encoding="utf-8", newline="") as fh:
        return fh.read()


def write_text(p: Path, text: str) -> None:
    with open(p, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def _tally(report: MutationReport) -> None:
    for st in report.files.values():
        st.killed = st.survived = st.timeout = st.invalid = st.skipped = 0
    for r in report.results:
        st = report.files.get(r.mutant.path)
        if st is None:
            continue
        setattr(st, r.status, getattr(st, r.status) + 1)
