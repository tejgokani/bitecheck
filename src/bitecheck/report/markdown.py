"""Markdown summary for PR comments and GitHub job summaries."""

from __future__ import annotations

from ..evidence import ERROR, WARN, Verdict
from ..plan import Plan
from ..probes import claims as C
from ..probes import mutants as M

MAX = 25


def render(plan: Plan, verdict: Verdict, cmd: str) -> str:
    icon = {"ok": "✅", WARN: "⚠️", ERROR: "❌"}[verdict.worst]
    word = {"ok": "PASS", WARN: "REVIEW", ERROR: "FAIL"}[verdict.worst]
    out = [f"## {icon} bitecheck: {word}", ""]
    mut = next((p for p in verdict.probes if p.name == "mutants" and isinstance(p.data, M.MutationReport)), None)
    if mut and mut.data.score is not None:
        rep = mut.data
        k = sum(1 for r in rep.counted if r.status != M.SURVIVED)
        out.append(f"**{k} of {len(rep.counted)}** deliberately broken changed lines were caught by the tests "
                   f"(**{rep.score:.0%}**, gate {verdict.min_score:.0%}).")
        out.append("")
        if rep.survivors:
            out += ["| Line | Change that no test noticed |", "|---|---|"]
            for r in rep.survivors[:MAX]:
                m = r.mutant
                desc = m.describe().replace("|", "\\|")  # no backslashes inside f-strings on 3.11
                out.append(f"| `{m.path}:{m.line}` | {desc} |")
            if len(rep.survivors) > MAX:
                out.append(f"| … | {len(rep.survivors) - MAX} more |")
            out.append("")
    out += ["| Probe | Result |", "|---|---|"]
    for p in verdict.probes:
        dot = "⚪" if p.status == "skipped" else {"ok": "🟢", WARN: "🟡", ERROR: "🔴"}[p.worst]
        out.append(f"| {dot} {p.name} | {p.summary.replace('|', '/')} |")
    out.append("")
    claims = next((p for p in verdict.probes if p.name == "claims" and isinstance(p.data, dict)), None)
    if claims and claims.data.get("claims"):
        out += ["**Agent claims**", ""]
        for c in claims.data["claims"]:
            if isinstance(c, C.Claim):
                mark = {"supported": "✅", "contradicted": "❌", "unverified": "❔"}[c.verdict]
                out.append(f"- {mark} “{c.quote}” — {c.evidence}")
        out.append("")
    issues = [f for f in verdict.findings if f.severity in (ERROR, WARN)
              and not (f.probe == "mutants" and f.code == "LINES_UNCHECKED") and f.probe != "claims"]
    if issues:
        out += ["<details><summary>Findings</summary>", ""]
        for f in issues:
            out.append(f"- **{f.code}** ({f.probe}): {f.message}")
            for it in f.items[:8]:
                out.append(f"  - `{it}`")
        out += ["", "</details>", ""]
    out.append(f"<sub>tests: `{cmd}` · base `{plan.base[:12]}` · "
               "[bitecheck](https://github.com/tejgokani/bitecheck): execution evidence, no LLM judgement</sub>")
    return "\n".join(out) + "\n"
