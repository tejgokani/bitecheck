"""Feedback written *for the agent*: short, ranked, actionable, hard to game."""

from __future__ import annotations

from pathlib import Path

from ..evidence import ERROR, WARN, Verdict
from ..plan import Plan
from ..probes import mutants as M

MAX_SURVIVORS = 15


def render(plan: Plan, verdict: Verdict, round_no: int | None = None, max_rounds: int | None = None,
           tree: Path | None = None, blocking: bool = True) -> str:
    if blocking:
        head = ("bitecheck verified your change by re-running the tests and deliberately breaking the lines you "
                "changed. It is not done yet. Fix the items below, then finish again.")
    else:
        head = ("bitecheck verified your change. It passes the gate; the items below are worth a look but do not "
                "block.")
    lines = [head, ""]
    n = 0
    mut = next((p for p in verdict.probes if p.name == "mutants"), None)
    if mut is not None and isinstance(mut.data, M.MutationReport) and mut.data.survivors:
        rep = mut.data
        n += 1
        counted = rep.counted
        killed = sum(1 for r in counted if r.status != M.SURVIVED)
        lines.append(f"{n}. Your tests do not check {len(rep.survivors)} of the {len(counted)} changed lines "
                     f"({killed} caught). Each change below was made to your code and every test still passed:")
        src_cache: dict[str, list[str]] = {}
        root = tree or plan.repo
        for r in rep.survivors[:MAX_SURVIVORS]:
            m = r.mutant
            if m.path not in src_cache:
                try:
                    src_cache[m.path] = (root / m.path).read_text(encoding="utf-8", errors="replace").splitlines()
                except OSError:
                    src_cache[m.path] = []
            src = src_cache[m.path]
            code = src[m.line - 1].strip() if 0 < m.line <= len(src) else ""
            lines.append(f"   - {m.path}:{m.line}: {m.describe()}   in: {code[:100]}")
        if len(rep.survivors) > MAX_SURVIVORS:
            lines.append(f"   - … and {len(rep.survivors) - MAX_SURVIVORS} more")
        lines.append("   For each line, add or strengthen a test assertion that would fail if that line were wrong. "
                     "Assert on the actual values the code produces. Do not delete, skip or weaken tests, and do "
                     "not add ignore pragmas: those are detected.")
        lines.append("")
    for f in verdict.findings:
        if f.probe == "mutants" or f.severity not in (ERROR, WARN):
            continue
        n += 1
        lines.append(f"{n}. [{f.code}] {f.message}")
        for it in f.items[:6]:
            lines.append(f"   - {it}")
        if f.hint:
            lines.append(f"   → {f.hint}")
        lines.append("")
    if n == 0:
        return "bitecheck: verified. No unchecked changed lines and no red flags."
    if round_no is not None and max_rounds is not None:
        lines.append(f"(bitecheck round {round_no} of {max_rounds}. If something above is wrong or a mutant is "
                     "genuinely equivalent, say so explicitly in your final message instead of working around it.)")
    return "\n".join(lines).rstrip() + "\n"
