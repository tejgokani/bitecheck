"""The tamper probe: static red flags in the diff. Cheap, instant, no execution.

These are the shortcuts agents take to make work *look* done: skipped or
focused tests, deleted assertions, suppressed type/lint errors, swallowed
exceptions, loosened CI gates, and special-cased literals copied from tests.
"""

from __future__ import annotations

import re
import time

from ..config import CONFIG_NAME, Config
from ..core import classify, git
from ..evidence import ERROR, WARN, Finding, ProbeResult
from ..plan import Plan

NAME = "tamper"

_SKIP = re.compile(
    r"@pytest\.mark\.(?:skip|xfail)\b|\bpytest\.skip\(|@unittest\.skip|\bself\.skipTest\(|"
    r"\b(?:it|test|describe|context)\.(?:skip|todo)\b|\bx(?:it|test|describe)\(|\bt\.Skip(?:f|Now)?\(|"
    r"#\[ignore\]|@Disabled\b|@Ignore\b|\[Ignore\]|^\s*skip\b"
)
_FOCUS = re.compile(r"\b(?:it|test|describe|context)\.only\b|\bf(?:it|describe)\(|\bfocus:\s*true")
_ASSERT = re.compile(
    r"\bassert\w*\b|\bexpect\s*\(|\bshould\b|\.to(?:Be|Equal|Have|Throw|Match|Contain)|\bt\.(?:Error|Fatal|Fail)|"
    r"\brequire\.\w+\(|\bXCTAssert|\bassert_eq!|\bassert_ne!|\bmust_equal\b|\bverify\("
)
_SUPPRESS = re.compile(
    r"#\s*type:\s*ignore|#\s*noqa|#\s*pylint:\s*disable|#\s*pyright:\s*ignore|@ts-ignore|@ts-expect-error|@ts-nocheck|"
    r"eslint-disable|biome-ignore|#\[allow\(|//\s*nolint|@SuppressWarnings|rubocop:disable|NOLINT|#\s*nosec|"
    r"#\s*bitecheck:\s*ignore|pragma:\s*no\s*mutate"
)
_SUPPRESS_TS = re.compile(r"\bas any\b|:\s*any\b(?!\s*\()")
_SWALLOW = re.compile(
    r"\bcatch\s*(?:\([^)]*\))?\s*\{\s*\}|\bexcept(?:\s+[\w.]+(?:\s+as\s+\w+)?)?\s*:\s*(?:pass|\.\.\.)\s*$|"
    r"^\s*_\s*=\s*err\b|\.catch\(\s*\(\)\s*=>\s*(?:\{\s*\}|null|undefined)\s*\)|rescue\s*(?:=>\s*\w+)?\s*;?\s*nil\b"
)
_GATE = re.compile(
    r"\|\|\s*true\b|\|\|\s*exit\s+0|continue-on-error:\s*true|allow_failure:\s*true|--passWithNoTests|"
    r"--no-verify|\bset\s+\+e\b|--deselect\b|-k\s+['\"]?not\s|--ignore[= ]|--exitzero|--exit-zero|"
    r"\bskip_tests?\b\s*[:=]\s*true|SKIP_TESTS"
)
_THRESHOLD = re.compile(r"(fail_under|fail-under|--cov-fail-under|coverageThreshold|minimum_coverage|min_score|"
                        r"\"(?:branches|functions|lines|statements)\")\D{0,8}(\d+(?:\.\d+)?)")
_COND_LITERAL = re.compile(r"(?:\bif\b|\belif\b|\bcase\b|\bwhen\b|===?|!==?|\bswitch\b)[^\n]*")
_LITERAL = re.compile(r"\"([^\"\\]{3,40})\"|'([^'\\]{3,40})'|(?<![\w.])(\d{2,})(?![\w.])")


def F(code, sev, msg, items=None, path=None, line=None, hint=None) -> Finding:
    return Finding(NAME, code, sev, msg, items or [], path=path, line=line, hint=hint)


def run(plan: Plan, cfg: Config) -> ProbeResult:
    start = time.monotonic()
    diffs = git.file_diffs(plan.repo, plan.base, plan.head, plan.changes)
    test_paths = {c.path for c in plan.test_changes}
    findings: list[Finding] = []
    skips, focus, suppress, swallow, gate = [], [], [], [], []
    removed_asserts = added_asserts = 0
    assert_files: list[str] = []
    test_added_text: list[str] = []

    for d in diffs:
        is_test = d.path in test_paths
        is_harness = classify.is_harness(d.path, cfg.harness_patterns) or d.path.startswith(".github/")
        if is_test:
            test_added_text += [t for _, t in d.added]
            r = sum(1 for t in d.removed if _ASSERT.search(t))
            a = sum(1 for _, t in d.added if _ASSERT.search(t))
            if r > a:
                assert_files.append(f"{d.path}: {r} assertion line(s) removed, {a} added")
            removed_asserts += r
            added_asserts += a
        prev_added = None
        for ln, text in d.added:
            loc = f"{d.path}:{ln}: {text.strip()[:100]}"
            if is_test and _SKIP.search(text):
                skips.append(loc)
            if is_test and _FOCUS.search(text):
                focus.append(loc)
            if not is_test and (_SUPPRESS.search(text) or (
                    d.path.endswith((".ts", ".tsx", ".mts", ".cts")) and _SUPPRESS_TS.search(text))):
                suppress.append(loc)
            if _SWALLOW.search(text):
                swallow.append(loc)
            elif re.fullmatch(r"\s*(?:pass|\.\.\.)\s*", text) and prev_added is not None and prev_added[0] == ln - 1 and \
                    re.match(r"\s*except\b[^:]*:\s*(?:#.*)?$", prev_added[1]):
                swallow.append(f"{d.path}:{ln - 1}: {prev_added[1].strip()} pass")
            prev_added = (ln, text)
            if is_harness and _GATE.search(text):
                gate.append(loc)
        if is_harness:
            gate += _lowered_thresholds(d)

    if skips:
        findings.append(F("TESTS_SKIPPED", WARN, "skip/xfail markers were added to tests", skips,
                          hint="remove the skip and make the test pass"))
    if focus:
        findings.append(F("TESTS_FOCUSED", ERROR, "focused tests (.only / fit) were added: the rest of the suite "
                          "silently stops running", focus, hint="remove .only/fit"))
    if assert_files:
        findings.append(F("ASSERTIONS_REMOVED", WARN, "more assertion lines were removed than added in test files",
                          assert_files, hint="restore the removed assertions or replace them with equivalent checks"))
    if suppress:
        findings.append(F("CHECKS_SUPPRESSED", WARN, "type/lint suppressions were added to code", suppress,
                          hint="fix the underlying type or lint error instead of suppressing it"))
    if swallow:
        findings.append(F("ERRORS_SWALLOWED", WARN, "exceptions/errors are caught and silently ignored", swallow,
                          hint="handle or propagate the error"))
    if gate:
        findings.append(F("GATE_LOOSENED", ERROR, "test or CI gates were loosened", gate,
                          hint="revert the change to the gate"))
    if any(c.path == CONFIG_NAME for c in plan.changes):
        findings.append(F("CONFIG_EDITED", WARN, f"{CONFIG_NAME} was edited; bitecheck still uses the base version"))
    snaps = [c.path for c in plan.changes if c.path.endswith(".snap") or "__snapshots__/" in c.path]
    if snaps:
        findings.append(F("SNAPSHOTS_REWRITTEN", WARN, "snapshot files were updated; confirm the new snapshots are "
                          "correct rather than regenerated to pass", snaps))
    special = _special_cases(diffs, test_paths, test_added_text)
    if special:
        special = _unexplained(plan, test_paths, special)
    if special:
        findings.append(F("SPECIAL_CASE_SUSPECT", WARN,
                          "new code branches on a literal that also appears in the changed tests; this is how "
                          "agents hard-code the expected answer", special,
                          hint="implement the general rule instead of special-casing test inputs"))
    n_flags = len(findings)
    summary = "no red flags" if not n_flags else f"{n_flags} red flag type(s)"
    return ProbeResult(NAME, "ran", summary, findings, elapsed=time.monotonic() - start)


def _repo_text(plan: Plan, skip: set[str], cap: int = 8_000_000) -> dict[str, str]:
    """Head contents of non-test text files (docs, specs, other code), size-capped."""
    if plan.head == git.WORKTREE:
        names = git._split_z(git._git(plan.repo, "ls-files", "-c", "-o", "--exclude-standard", "-z"))
    else:
        names = git._split_z(git._git(plan.repo, "ls-tree", "-r", "-z", "--name-only", plan.head))
    out: dict[str, str] = {}
    total = 0
    for name in names:
        if name in skip or total > cap:
            continue
        data = git.read_head_file(plan.repo, plan.head, name)
        if not data or len(data) > 256_000 or b"\0" in data[:4000]:
            continue
        total += len(data)
        out[name] = data.decode("utf-8", errors="replace")
    return out


def _unexplained(plan: Plan, test_paths: set[str], flagged: list[str]) -> list[str]:
    """Drop special-case suspects whose input literal is documented or used elsewhere.

    `if zone == "domestic": return 0.0` is a business rule when "domestic" appears in
    the spec or elsewhere in the code; `if year == 1900: return 29` is suspicious when
    1900 appears nowhere but the tests and this one line.
    """
    corpus = _repo_text(plan, test_paths)
    keep = []
    for item in flagged:
        m = re.search(r"\(input '([^']*)' and result", item)
        path_line = item.split(":", 2)
        lit = m.group(1) if m else None
        if lit is None:
            keep.append(item)
            continue
        pat = re.compile(rf"(?<![\w.]){re.escape(lit)}(?![\w.])")
        hits = 0
        for name, text in corpus.items():
            n = len(pat.findall(text))
            if name == path_line[0]:
                n -= 1  # the suspicious line itself
            hits += max(n, 0)
        if hits == 0:
            keep.append(item)
    return keep


def _lowered_thresholds(d: git.FileDiff) -> list[str]:
    old = {}
    for t in d.removed:
        for m in _THRESHOLD.finditer(t):
            old[m.group(1)] = float(m.group(2))
    out = []
    for ln, t in d.added:
        for m in _THRESHOLD.finditer(t):
            key, val = m.group(1), float(m.group(2))
            if key in old and val < old[key]:
                out.append(f"{d.path}:{ln}: {key} lowered {old[key]:g} → {val:g}")
    return out


_BODY_LITERAL = re.compile(r"(?:\breturn\b|=>|(?<![=!<>])=(?!=))\s*(?P<lit>\"[^\"\\]{1,40}\"|'[^'\\]{1,40}'|-?\d+(?:\.\d+)?|True|False|true|false)\s*[;,)]?\s*$")


def _special_cases(diffs: list[git.FileDiff], test_paths: set[str], test_text: list[str]) -> list[str]:
    """Flag `if <test input>: return <test expectation>` shapes.

    Branching on a literal that the tests also use is normal (coupon codes,
    enum values). It becomes suspicious when the branch *also* produces a
    literal that the tests expect: that is the hard-coded-answer pattern.
    """
    if not test_text:
        return []
    corpus = "\n".join(test_text)

    def in_tests(lit: str) -> bool:
        return bool(re.search(rf"(?<![\w.]){re.escape(lit)}(?![\w.])", corpus))

    out = []
    for d in diffs:
        if d.path in test_paths:
            continue
        added = dict(d.added)
        for ln, text in d.added:
            cond = _COND_LITERAL.search(text)
            if not cond:
                continue
            cond_text = cond.group(0)
            one = re.search(r"\)\s*return\b", cond_text)
            if one:
                cond_text = cond_text[: one.start() + 1]
            cond_text = re.split(r":|\{|\bthen\b|\?", cond_text, maxsplit=1)[0]
            cond_lits = [m.group(1) or m.group(2) or m.group(3) for m in _LITERAL.finditer(cond_text)]
            cond_lits = [x for x in cond_lits if x and in_tests(x)]
            if not cond_lits:
                continue
            # The branch body: rest of this line after ':'/'{'/'then', plus the next two added lines.
            tail = re.split(r":|\{|\bthen\b|\?", text, maxsplit=1)
            body = ([tail[1]] if len(tail) > 1 else []) + [added[k] for k in (ln + 1, ln + 2) if k in added]
            one_line = re.search(r"\)\s*(return\b.*)$", text)  # C/JS: if (x === 'a') return 'b';
            if one_line:
                body.insert(0, one_line.group(1))
            for b in body:
                m = _BODY_LITERAL.search(b.strip())
                if not m:
                    continue
                lit = m.group("lit").strip("\"'")
                if lit and in_tests(lit) and lit not in cond_lits:
                    out.append(f"{d.path}:{ln}: {text.strip()[:80]} → {b.strip()[:40]}  "
                               f"(input {cond_lits[0]!r} and result {lit!r} both appear in the tests)")
                    break
    return out
