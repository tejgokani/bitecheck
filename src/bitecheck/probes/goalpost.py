"""The goalpost probe: did the change only pass because the tests changed?

    variant      code   tests   question
    base         old    old     control
    head         new    new     does the change pass its own tests?
    old_tests    new    old     do the ORIGINAL tests still pass?  (goalpost)
    new_tests    old    new     do the NEW tests detect anything?  (vacuity)

Ported from fliptest (https://github.com/tejgokani/fliptest).
"""

from __future__ import annotations

import re
import time

from ..config import Config
from ..core import git, junit
from ..core.runner import RunResult, run_command
from ..evidence import ERROR, INFO, WARN, Finding, ProbeResult
from ..plan import Plan
from ..workspace import Workspace

NAME = "goalpost"
_UNSTABLE_ID = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}|\d+\.\d{6,}|\d{10,}|0x[0-9a-f]{8,}", re.I)


def _unstable(tid: str) -> bool:
    return bool(_UNSTABLE_ID.search(tid))


def run(plan: Plan, cfg: Config, ws: Workspace, progress=None, head_result: RunResult | None = None) -> ProbeResult:
    say = progress or (lambda msg: None)
    start = time.monotonic()
    runs: dict[str, RunResult] = {}
    cross = bool(plan.test_changes and plan.code_changes)

    def go(variant: str, tree) -> RunResult:
        say(f"goalpost: running {variant}")
        if cfg.junit:
            (tree / cfg.junit).unlink(missing_ok=True)
        res = run_command(cfg.test_cmd, tree, variant, cfg.timeout, ws.logs / f"{variant}.log")
        if cfg.junit:
            try:
                res.tests = junit.parse(tree / cfg.junit)
            except junit.JUnitError as exc:
                res.junit_error = str(exc)
        return res

    runs["head"] = head_result if head_result is not None else go("head", ws.head())
    runs["base"] = go("base", ws.base())
    if cross:
        old = ws.copy(ws.head(), "old_tests")
        new = ws.copy(ws.base(), "new_tests")
        for ch in plan.test_changes:
            if ch.status == "A":
                git.remove_entry(old, ch.path)
            else:
                git.copy_entry(ws.base() / ch.path, old / ch.path, old)
            if ch.status == "D":
                git.remove_entry(new, ch.path)
            else:
                git.copy_entry(ws.head() / ch.path, new / ch.path, new)
        runs["old_tests"] = go("old_tests", old)
        runs["new_tests"] = go("new_tests", new)
    findings = judge(plan, runs)
    summary = _summary(runs)
    return ProbeResult(NAME, "ran", summary, findings, data=runs, elapsed=time.monotonic() - start)


def run_head(cfg: Config, ws: Workspace) -> RunResult:
    """The plain head run, shared with the claims probe."""
    tree = ws.copy(ws.head(), "head_run")
    if cfg.junit:
        (tree / cfg.junit).unlink(missing_ok=True)
    res = run_command(cfg.test_cmd, tree, "head", cfg.timeout, ws.logs / "head.log")
    if cfg.junit:
        try:
            res.tests = junit.parse(tree / cfg.junit)
        except junit.JUnitError as exc:
            res.junit_error = str(exc)
    return res


def _summary(runs: dict[str, RunResult]) -> str:
    def cell(r: RunResult | None) -> str:
        if r is None:
            return "-"
        return "timeout" if r.timed_out else "pass" if r.passed else "FAIL"
    return " · ".join(f"{k} {cell(runs.get(k))}" for k in ("head", "base", "old_tests", "new_tests") if k in runs)


def F(code, sev, msg, items=None, hint=None) -> Finding:
    return Finding(NAME, code, sev, msg, items or [], hint=hint)


def judge(plan: Plan, runs: dict[str, RunResult]) -> list[Finding]:
    f: list[Finding] = []
    head, base = runs["head"], runs.get("base")
    old, new = runs.get("old_tests"), runs.get("new_tests")
    cross = bool(plan.test_changes and plan.code_changes)

    for name, res in runs.items():
        if res.timed_out:
            f.append(F("TIMEOUT", ERROR, f"{name} run timed out; result is inconclusive"))
        elif res.exit_code is None:
            f.append(F("RUN_ERROR", ERROR, f"{name} run could not start: {res.error}"))
        if res.junit_error:
            f.append(F("JUNIT_UNREADABLE", WARN, f"{name}: {res.junit_error}; falling back to exit codes"))

    if not head.passed and head.exit_code is not None:
        f.append(F("HEAD_FAILS", ERROR, "the test suite fails on the change itself",
                   hint="make the full test suite pass before finishing"))
    if base is not None and not base.passed and base.exit_code is not None:
        f.append(F("BASE_FAILS", INFO, "the suite already failed before the change"))
        if base.tests and head.tests:
            fixed = sorted(t for t, o in base.tests.items() if o in ("fail", "error") and head.tests.get(t) == "pass")
            if fixed:
                f.append(F("FIXED", INFO, "tests that failed before and pass now", fixed))

    deleted = [c.path for c in plan.test_changes if c.status == "D"]
    if deleted:
        f.append(F("TEST_FILES_DELETED", WARN, "test files were deleted", deleted))

    if cross and old is not None and old.exit_code is not None and not old.timed_out:
        moved = _regressions(base, old) if (base and base.tests and old.tests is not None) else None
        if moved:
            f.append(F("GOALPOST_MOVED", ERROR,
                       "tests that passed before the change fail against the new code and pass only in their "
                       "edited form (or were removed)", moved,
                       hint="restore the original assertions, or explain exactly why the old expectation was wrong"))
        elif moved == [] and not old.passed and head.passed:
            f.append(F("GOALPOST_INCONCLUSIVE", WARN,
                       "the original suite fails against the new code but no single test regression was "
                       "identified (collection or import error?)"))
        elif moved is None and not old.passed and head.passed:
            if base is None or base.passed:
                f.append(F("GOALPOST_MOVED", ERROR,
                           "the original test suite fails against the new code and only the edited suite passes",
                           hint="restore the original tests, or explain why the old expectations were wrong"))
            else:
                f.append(F("GOALPOST_INCONCLUSIVE", WARN,
                           "the original tests fail against the new code, but they also failed before"))

    unstable = sorted({t for r in runs.values() if r.tests for t in r.tests if _unstable(t)})
    if base is not None and base.tests and head.tests:
        gone = [t for t, o in base.tests.items() if o == "pass" and t not in head.tests and not _unstable(t)]
        if cross and old is not None and old.tests is not None:
            gone = [t for t in gone if t in old.tests]
        if gone:
            f.append(F("TESTS_DISAPPEARED", WARN, "tests that passed before no longer run at all", sorted(gone)))
        skipped = sorted(t for t, o in base.tests.items() if o == "pass" and head.tests.get(t) == "skip")
        if skipped:
            f.append(F("TESTS_NEWLY_SKIPPED", WARN, "tests that passed before are now skipped", skipped,
                       hint="un-skip these tests and make them pass"))

    if cross and new is not None and new.exit_code is not None and not new.timed_out:
        if new.tests and head.tests:
            known = set(base.tests) if (base and base.tests) else set()
            added = [t for t in head.tests if t not in known and head.tests[t] == "pass" and not _unstable(t)]
            vacuous = sorted(t for t in added if new.tests.get(t) == "pass")
            caught = sorted(t for t in added if new.tests.get(t) in ("fail", "error")
                            or (t not in new.tests and not new.passed))
            if vacuous:
                f.append(F("VACUOUS_TESTS", WARN,
                           "new tests also pass on the old code, so they do not detect this change", vacuous,
                           hint="make these tests assert the new behaviour"))
            if caught:
                f.append(F("FAIL_TO_PASS", INFO, "new tests fail on the old code and pass on the new code", caught))
        elif new.passed and head.passed:
            f.append(F("VACUOUS_TESTS", WARN,
                       "the edited test suite also passes on the old code, so the test changes do not detect "
                       "this change", hint="add a test that fails without your code change"))
        elif not new.passed and head.passed:
            f.append(F("FAIL_TO_PASS", INFO, "the edited tests fail on the old code and pass on the new code"))
    if unstable:
        f.append(F("UNSTABLE_TEST_IDS", INFO,
                   f"{len(unstable)} test id(s) embed run-dependent values and were not matched across runs",
                   unstable))
    return f


def _regressions(base: RunResult, old: RunResult) -> list[str]:
    regressed = [t for t, o in base.tests.items()
                 if o == "pass" and not _unstable(t) and old.tests.get(t) in ("fail", "error")]
    if not regressed and not old.passed:
        regressed = [t for t, o in base.tests.items()
                     if o == "pass" and not _unstable(t) and t not in old.tests]
    return sorted(regressed)
