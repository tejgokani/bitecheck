"""The claims probe: hold the agent to what it said.

The agent's final message is scanned for checkable claims ("all tests pass",
"added tests for X", "comprehensive test coverage", "no behaviour change",
"didn't touch the tests"). Each claim is checked against bitecheck's *own*
re-execution of the change, never against what the agent says it ran.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass

from ..core.runner import RunResult
from ..evidence import ERROR, INFO, WARN, Finding, ProbeResult
from ..plan import Plan
from ..transcripts import AgentMessage

NAME = "claims"

SUPPORTED, CONTRADICTED, UNVERIFIED = "supported", "contradicted", "unverified"

_NEG = r"(?<!\bnot )(?<!n't )(?<!\bno )"
PATTERNS = {
    "tests_pass": re.compile(
        r"\b(?:all|every|the(?: full)?|full)\s+(?:\d+\s+)?(?:unit\s+)?(?:tests?|test suite|specs?)\b[^.\n]{0,30}?"
        r"\b(?:pass(?:es|ed|ing)?|green|succeed(?:s|ed)?)\b|\btests?\s+(?:are\s+|now\s+)*(?:all\s+)?(?:pass(?:ing|es)?|green)\b"
        r"|\b\d+\s+(?:tests?\s+)?passed\b|\bsuite\s+(?:is\s+)?(?:green|passing)\b", re.I),
    "tests_added": re.compile(
        r"\b(?:added|wrote|written|created|include[sd]?|implemented|adds)\b[^.\n]{0,40}?\b(?:unit\s+|regression\s+|new\s+)?"
        r"tests?\b(?! (?:file )?was not)", re.I),
    "thorough": re.compile(
        r"\b(?:comprehensive|thorough|extensive|full|complete|exhaustive|robust)\b[^.\n]{0,25}?\b(?:tests?|test coverage|"
        r"coverage|test suite)\b|\b100\s*%\s*(?:test\s+)?coverage\b|\bfully\s+(?:tested|covered)\b"
        r"|\bcovers?\s+(?:all|every)\s+(?:the\s+)?(?:edge|corner)\s+cases\b", re.I),
    "no_behavior_change": re.compile(
        r"\bno\s+(?:functional|behaviou?ral|logic)\s+changes?\b|\bbehaviou?r\s+(?:is\s+|remains\s+)?unchanged\b|"
        r"\b(?:pure|purely a|only a|just a)\s+refactor|\bwithout\s+changing\s+(?:the\s+|any\s+)?(?:behaviou?r|functionality)\b",
        re.I),
    "tests_untouched": re.compile(
        r"\b(?:didn'?t|did not|without|no)\s+(?:modify|modifying|change|changing|touch|touching|edit|editing)\w*\s+"
        r"(?:any\s+|the\s+)?(?:existing\s+)?tests?\b|\btests?\s+(?:were|are)\s+(?:left\s+)?(?:untouched|unchanged|unmodified)\b",
        re.I),
}
LABELS = {
    "tests_pass": "the tests pass",
    "tests_added": "tests were added",
    "thorough": "the tests are thorough",
    "no_behavior_change": "behaviour did not change",
    "tests_untouched": "existing tests were not modified",
}


@dataclass
class Claim:
    kind: str
    quote: str
    verdict: str = UNVERIFIED
    evidence: str = ""


NEGATED = {
    "tests_pass": re.compile(
        r"\b(?:don'?t|do not|doesn'?t|does not|didn'?t|did not|not|never|won'?t|can'?t|cannot|isn'?t|aren'?t)\b"
        r"[^.\n]{0,20}\b(?:pass|green)|\bnot all\b|\b(?:still|now)\s+fail|\b[1-9]\d*\s+(?:tests?\s+)?fail(?:ed|ing|s|ures?)?\b",
        re.I),
    "tests_added": re.compile(
        r"\b(?:no|didn'?t|did not|haven'?t|have not|without|wasn'?t|weren'?t)\b[^.\n]{0,20}\b(?:add|wr[oi]te|tests?)\b",
        re.I),
    "thorough": re.compile(r"\b(?:not|isn'?t|aren'?t|lacks?|missing|no|without)\b[^.\n]{0,20}\b(?:comprehensive|"
                           r"thorough|coverage|extensive)\b", re.I),
    "no_behavior_change": re.compile(r"\b(?:not|isn'?t)\s+(?:a\s+)?(?:pure\s+)?refactor", re.I),
    "tests_untouched": re.compile(r"$^"),
}


def extract(text: str) -> list[Claim]:
    claims: list[Claim] = []
    # Drop fenced code blocks and quoted output; claims live in prose.
    prose = re.sub(r"```.*?```", " ", text, flags=re.S)
    sentences = [s for s in re.split(r"(?<=[.!?])\s+|\n+|;\s+", prose) if s.strip()]
    for kind, pat in PATTERNS.items():
        for s in sentences:
            m = pat.search(s)
            if m and not NEGATED[kind].search(s):
                quote = " ".join(s.strip().split())
                claims.append(Claim(kind, quote[:160]))
                break
    return claims


def run(plan: Plan, message: AgentMessage | None, *, head: RunResult | None, score: float | None,
        min_score: float, survivors: int, killed: int, goalpost_codes: set[str]) -> ProbeResult:
    start = time.monotonic()
    if message is None:
        return ProbeResult(NAME, "skipped", "no agent message found (use --message/--transcript, or run as a hook)")
    claims = extract(message.text)
    if not claims:
        return ProbeResult(NAME, "ran", "no checkable claims in the agent's final message",
                           [Finding(NAME, "NO_CLAIMS", INFO, f"read {message.agent} message from {message.source}")])
    test_changed = bool(plan.test_changes)
    test_added = any(c.status == "A" for c in plan.test_changes) or test_changed
    for c in claims:
        if c.kind == "tests_pass":
            if head is None:
                c.evidence = "suite was not run"
            elif head.timed_out:
                c.verdict, c.evidence = CONTRADICTED, "bitecheck's run of the suite timed out"
            elif head.passed:
                c.verdict, c.evidence = SUPPORTED, f"bitecheck re-ran the suite: passed in {head.duration:.1f}s"
                if "TESTS_NEWLY_SKIPPED" in goalpost_codes or "TESTS_DISAPPEARED" in goalpost_codes:
                    c.verdict, c.evidence = CONTRADICTED, "passes, but only because previously passing tests were " \
                                                          "skipped or removed"
                if "GOALPOST_MOVED" in goalpost_codes:
                    c.verdict, c.evidence = CONTRADICTED, "passes only with edited tests; the original tests fail " \
                                                          "against the new code"
            else:
                c.verdict, c.evidence = CONTRADICTED, f"bitecheck re-ran the suite: exit code {head.exit_code}"
        elif c.kind == "tests_added":
            if not test_added:
                c.verdict, c.evidence = CONTRADICTED, "no test files were added or changed"
            elif "VACUOUS_TESTS" in goalpost_codes:
                c.verdict, c.evidence = CONTRADICTED, "test changes exist, but they also pass on the old code: " \
                                                      "they do not test this change"
            elif score is not None and survivors and killed == 0:
                c.verdict, c.evidence = CONTRADICTED, f"tests changed, but none of the {survivors} mutant(s) on the " \
                                                      "changed lines were caught"
            else:
                c.verdict, c.evidence = SUPPORTED, f"{len(plan.test_changes)} test file(s) changed"
        elif c.kind == "thorough":
            if score is None:
                c.evidence = "no mutation score was measured"
            elif score >= min_score:
                c.verdict, c.evidence = SUPPORTED, f"mutation score on changed lines {score:.0%}"
            else:
                c.verdict, c.evidence = CONTRADICTED, (f"only {killed} of {killed + survivors} deliberately broken "
                                                       f"changed lines were caught by the tests ({score:.0%})")
        elif c.kind == "no_behavior_change":
            if "GOALPOST_MOVED" in goalpost_codes:
                c.verdict, c.evidence = CONTRADICTED, "the original tests fail against the new code"
            elif plan.code_changes and head is not None and head.passed and not test_changed:
                c.verdict, c.evidence = SUPPORTED, "the unchanged test suite still passes"
            else:
                c.evidence = "tests were changed, so the original suite is the only reference"
                if "goalpost:old_tests_pass" in goalpost_codes:
                    c.verdict, c.evidence = SUPPORTED, "the original tests pass against the new code"
        elif c.kind == "tests_untouched":
            if test_changed:
                c.verdict = CONTRADICTED
                c.evidence = "test files changed: " + ", ".join(x.path for x in plan.test_changes[:5])
            else:
                c.verdict, c.evidence = SUPPORTED, "no test files changed"
    findings = []
    bad = [c for c in claims if c.verdict == CONTRADICTED]
    for c in bad:
        findings.append(Finding(NAME, "CLAIM_CONTRADICTED", ERROR,
                                f"the agent claimed {LABELS[c.kind]}, but {c.evidence}", [f'"{c.quote}"'],
                                hint=f"either make the claim true or retract it: {LABELS[c.kind]}"))
    for c in claims:
        if c.verdict == SUPPORTED:
            findings.append(Finding(NAME, "CLAIM_SUPPORTED", INFO, f"{LABELS[c.kind]}: {c.evidence}", [f'"{c.quote}"']))
        elif c.verdict == UNVERIFIED:
            findings.append(Finding(NAME, "CLAIM_UNVERIFIED", INFO, f"{LABELS[c.kind]}: {c.evidence}", [f'"{c.quote}"']))
    summary = f"{len(claims)} claim(s): {len(bad)} contradicted"
    res = ProbeResult(NAME, "ran", summary, findings, data={"claims": claims, "agent": message.agent,
                                                           "source": message.source}, elapsed=time.monotonic() - start)
    return res


__all__ = ["run", "extract", "Claim", "SUPPORTED", "CONTRADICTED", "UNVERIFIED", "WARN"]
