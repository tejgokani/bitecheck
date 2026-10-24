"""Terminal report."""

from __future__ import annotations

import os

from ..evidence import ERROR, INFO, WARN, Verdict
from ..plan import Plan
from ..probes import mutants as M

MAX_ITEMS = 12


def color_enabled(stream) -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    return hasattr(stream, "isatty") and stream.isatty()


class Style:
    def __init__(self, on: bool):
        self.on = on

    def w(self, code: str, s: str) -> str:
        return f"\x1b[{code}m{s}\x1b[0m" if self.on else s

    def red(self, s): return self.w("31;1", s)
    def yellow(self, s): return self.w("33;1", s)
    def green(self, s): return self.w("32;1", s)
    def cyan(self, s): return self.w("36", s)
    def dim(self, s): return self.w("2", s)
    def bold(self, s): return self.w("1", s)


def bar(frac: float, width: int = 24) -> str:
    n = round(frac * width)
    return "█" * n + "░" * (width - n)


def render(plan: Plan, verdict: Verdict, cmd: str, stream, verbose: bool = False, workdir: str | None = None) -> str:
    st = Style(color_enabled(stream))
    out = [
        st.bold("bitecheck") + st.dim(f"  {plan.base[:12]} → {plan.head_label}  ·  "
                                      f"{len(plan.code_changes)} code / {len(plan.test_changes)} test file(s) changed"),
    ]
    if cmd:
        out.append(st.dim(f"  tests: {cmd}"))
    out.append("")
    mut = next((p for p in verdict.probes if p.name == "mutants"), None)
    if mut is not None and isinstance(mut.data, M.MutationReport) and mut.data.score is not None:
        rep = mut.data
        counted = rep.counted
        killed = sum(1 for r in counted if r.status != M.SURVIVED)
        score = rep.score
        paint = st.green if score >= verdict.min_score else st.red
        out.append(f"  {paint(bar(score))}  {paint(f'{killed} of {len(counted)}')} deliberately broken changed lines were caught"
                   f"  {st.dim(f'({score:.0%}, gate {verdict.min_score:.0%})')}")
        out.append("")
        for r in rep.survivors[:MAX_ITEMS]:
            m = r.mutant
            out.append(f"  {st.red('✗')} {st.cyan(f'{m.path}:{m.line}')}  {m.describe()}  "
                       f"{st.dim('survived: no test failed')}")
        if len(rep.survivors) > MAX_ITEMS:
            out.append(st.dim(f"    … {len(rep.survivors) - MAX_ITEMS} more (--json / --html)"))
        if verbose:
            for r in rep.results:
                if r.status != M.SURVIVED:
                    m = r.mutant
                    out.append(st.dim(f"  {'✓' if r.status in (M.KILLED, M.TIMEOUT) else '·'} {m.path}:{m.line}  "
                                      f"{m.describe()}  {r.status}{(' by ' + r.killed_by[0]) if r.killed_by else ''}"))
        if rep.survivors or verbose:
            out.append("")
    for p in verdict.probes:
        if p.status == "skipped":
            out.append(f"  {st.dim('○')} {p.name:<9} {st.dim(p.summary)}")
            continue
        icon = {"ok": st.green("●"), WARN: st.yellow("●"), ERROR: st.red("●")}[p.worst]
        out.append(f"  {icon} {st.bold(f'{p.name:<9}')} {p.summary}  {st.dim(f'{p.elapsed:.1f}s')}")
        for fd in p.findings:
            if fd.severity == INFO and not verbose and fd.code not in ("CLAIM_SUPPORTED", "FAIL_TO_PASS", "FIXED"):
                continue
            if p.name == "mutants" and fd.code == "LINES_UNCHECKED":
                continue  # already shown above
            tag = {ERROR: st.red("ERROR"), WARN: st.yellow("WARN "), INFO: st.dim("info ")}[fd.severity]
            out.append(f"      {tag} {fd.code}: {fd.message}")
            cap = MAX_ITEMS if fd.severity != INFO or verbose else 3
            for it in fd.items[:cap]:
                out.append(st.dim(f"            {it}"))
            if len(fd.items) > cap:
                out.append(st.dim(f"            … {len(fd.items) - cap} more"))
    if workdir:
        out += ["", st.dim(f"  snapshots and logs kept in {workdir}")]
    verdict_s = {"ok": st.green("PASS"), WARN: st.yellow("REVIEW"), ERROR: st.red("FAIL")}[verdict.worst]
    out += ["", f"  verdict: {verdict_s}"]
    return "\n".join(out)
