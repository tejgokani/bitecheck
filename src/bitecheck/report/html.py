"""Self-contained HTML report: no external requests, works offline, dark/light."""

from __future__ import annotations

import html as H
from datetime import UTC, datetime

from .. import __version__
from ..core import git
from ..evidence import ERROR, INFO, WARN, Verdict
from ..plan import Plan
from ..probes import claims as C
from ..probes import mutants as M

CONTEXT = 2

CSS = """
:root{--bg:#0b0d10;--panel:#12161b;--line:#1e242c;--fg:#e6e9ee;--mut:#8a94a3;--ok:#3ddc97;--bad:#ff5c6c;
--warn:#ffb547;--acc:#58a6ff;--code:#0f1318;--hl-bad:rgba(255,92,108,.12);--hl-ok:rgba(61,220,151,.08)}
@media (prefers-color-scheme:light){:root{--bg:#f6f7f9;--panel:#fff;--line:#e3e6ea;--fg:#14181d;--mut:#5d6672;
--ok:#0f9d63;--bad:#d42d40;--warn:#b26a00;--acc:#0b63ce;--code:#fafbfc;--hl-bad:rgba(212,45,64,.08);--hl-ok:rgba(15,157,99,.07)}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,sans-serif}
main{max-width:1080px;margin:0 auto;padding:32px 16px 64px}
h1{font-size:22px;margin:0;letter-spacing:-.01em}h2{font-size:15px;text-transform:uppercase;letter-spacing:.08em;
color:var(--mut);margin:36px 0 12px;font-weight:600}
.meta{color:var(--mut);font-size:13px;margin-top:4px;word-break:break-all}
.hero{display:grid;grid-template-columns:auto 1fr auto;gap:24px;align-items:center;background:var(--panel);
border:1px solid var(--line);border-radius:16px;padding:24px;margin-top:20px}
.ring{width:120px;height:120px}.ring text{font:700 26px/1 inherit;fill:var(--fg)}
.big{font-size:20px;font-weight:600}.sub{color:var(--mut);margin-top:6px}
.verdict{font-weight:800;font-size:14px;padding:8px 14px;border-radius:999px;letter-spacing:.06em}
.v-ok{background:rgba(61,220,151,.15);color:var(--ok)}.v-warn{background:rgba(255,181,71,.15);color:var(--warn)}
.v-error{background:rgba(255,92,108,.15);color:var(--bad)}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px}
.card b{display:block;font-size:13px;color:var(--mut);font-weight:600;text-transform:uppercase;letter-spacing:.06em}
.card span{display:block;margin-top:6px}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px;vertical-align:middle}
.d-ok{background:var(--ok)}.d-warn{background:var(--warn)}.d-error{background:var(--bad)}.d-skip{background:var(--mut)}
.file{background:var(--panel);border:1px solid var(--line);border-radius:12px;margin-bottom:16px;overflow:hidden}
.file header{padding:10px 14px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;
gap:12px;flex-wrap:wrap;font-weight:600}.file header small{color:var(--mut);font-weight:400}
.code{overflow-x:auto;background:var(--code);font:13px/1.55 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
.row{display:grid;grid-template-columns:52px 1fr;min-width:max-content}
.row .n{color:var(--mut);text-align:right;padding-right:12px;user-select:none}
.row pre{margin:0;white-space:pre;padding-right:16px}
.row.ch .n{color:var(--fg)}.row.bad{background:var(--hl-bad)}.row.good{background:var(--hl-ok)}
.gap{color:var(--mut);padding:2px 0 2px 64px}
.mut{grid-column:2;font:12px/1.4 ui-monospace,Menlo,monospace;padding:2px 0 6px;color:var(--mut)}
.mut .x{color:var(--bad);font-weight:700}.mut .k{color:var(--ok);font-weight:700}
table{width:100%;border-collapse:collapse;background:var(--panel);border:1px solid var(--line);border-radius:12px;
overflow:hidden;font-size:14px}td,th{padding:10px 12px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{color:var(--mut);font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.06em}
.chip{font-size:12px;font-weight:700;padding:2px 8px;border-radius:999px;white-space:nowrap}
.c-supported{background:rgba(61,220,151,.15);color:var(--ok)}.c-contradicted{background:rgba(255,92,108,.15);color:var(--bad)}
.c-unverified{background:rgba(138,148,163,.15);color:var(--mut)}
.f{background:var(--panel);border:1px solid var(--line);border-left-width:4px;border-radius:10px;padding:12px 14px;margin-bottom:10px}
.f.error{border-left-color:var(--bad)}.f.warn{border-left-color:var(--warn)}.f.info{border-left-color:var(--line)}
.f code{font-size:12px}.f ul{margin:6px 0 0;padding-left:18px;color:var(--mut);font:12px/1.5 ui-monospace,Menlo,monospace}
.f .hint{color:var(--acc);font-size:13px;margin-top:6px}
footer{margin-top:48px;color:var(--mut);font-size:12px;text-align:center}
@media (max-width:640px){.hero{grid-template-columns:1fr;text-align:center}.ring{margin:0 auto}}
"""


def _ring(score: float | None, ok: bool) -> str:
    r, c = 52, 2 * 3.14159 * 52
    frac = 0 if score is None else score
    color = "var(--ok)" if ok else "var(--bad)"
    label = "—" if score is None else f"{round(frac * 100)}%"
    return (f'<svg class="ring" viewBox="0 0 120 120" role="img" aria-label="mutation score {label}">'
            f'<circle cx="60" cy="60" r="{r}" fill="none" stroke="var(--line)" stroke-width="10"/>'
            f'<circle cx="60" cy="60" r="{r}" fill="none" stroke="{color}" stroke-width="10" stroke-linecap="round" '
            f'stroke-dasharray="{c * frac:.1f} {c:.1f}" transform="rotate(-90 60 60)"/>'
            f'<text x="60" y="69" text-anchor="middle">{label}</text></svg>')


def _e(s) -> str:
    return H.escape(str(s), quote=True)


def render(plan: Plan, verdict: Verdict, cmd: str) -> str:
    mut = next((p for p in verdict.probes if p.name == "mutants"), None)
    rep: M.MutationReport | None = mut.data if mut is not None and isinstance(mut.data, M.MutationReport) else None
    score = rep.score if rep else None
    counted = rep.counted if rep else []
    killed = sum(1 for r in counted if r.status != M.SURVIVED)
    ok = score is not None and score >= verdict.min_score
    vclass = {"ok": "v-ok", WARN: "v-warn", ERROR: "v-error"}[verdict.worst]
    vlabel = {"ok": "PASS", WARN: "REVIEW", ERROR: "FAIL"}[verdict.worst]
    if score is not None:
        headline = f"{killed} of {len(counted)} deliberately broken changed lines were caught by the tests"
        sub = (f"Each changed line was broken on purpose and the suite re-run. Gate: {verdict.min_score:.0%}. "
               f"{len(rep.survivors)} change(s) went unnoticed.")
    else:
        headline = "No mutation score measured"
        sub = next((p.summary for p in verdict.probes if p.name == "mutants"), "mutation probe not run")
    parts = [f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' "
             f"content='width=device-width,initial-scale=1'><title>bitecheck report</title><style>{CSS}</style>"
             f"</head><body><main>",
             f"<h1>bitecheck</h1><div class='meta'>{_e(plan.base[:12])} → {_e(plan.head_label)} · "
             f"{len(plan.code_changes)} code / {len(plan.test_changes)} test file(s) · tests: <code>{_e(cmd)}</code></div>",
             f"<section class='hero'>{_ring(score, ok)}<div><div class='big'>{_e(headline)}</div>"
             f"<div class='sub'>{_e(sub)}</div></div><div class='verdict {vclass}'>{vlabel}</div></section>",
             "<h2>Probes</h2><div class='cards'>"]
    for p in verdict.probes:
        d = "d-skip" if p.status == "skipped" else {"ok": "d-ok", WARN: "d-warn", ERROR: "d-error"}[p.worst]
        parts.append(f"<div class='card'><b><span class='dot {d}'></span>{_e(p.name)}</b><span>{_e(p.summary)}</span></div>")
    parts.append("</div>")

    if rep and rep.results:
        parts.append("<h2>Changed code, broken on purpose</h2>")
        by_file: dict[str, list[M.MutantResult]] = {}
        for r in rep.results:
            by_file.setdefault(r.mutant.path, []).append(r)
        for path in sorted(by_file):
            parts.append(_file_block(plan, path, by_file[path]))

    claims = next((p for p in verdict.probes if p.name == "claims" and isinstance(p.data, dict)), None)
    if claims and claims.data.get("claims"):
        who = claims.data.get("agent")
        who = f" ({_e(who)})" if who and who != "unknown" else ""
        parts.append(f"<h2>What the agent claimed{who}</h2><table>"
                     "<tr><th>Claim</th><th>Verdict</th><th>Evidence</th></tr>")
        for c in claims.data["claims"]:
            if isinstance(c, C.Claim):
                parts.append(f"<tr><td><b>{_e(C.LABELS[c.kind])}</b><div class='meta'>“{_e(c.quote)}”</div></td>"
                             f"<td><span class='chip c-{_e(c.verdict)}'>{_e(c.verdict)}</span></td>"
                             f"<td>{_e(c.evidence)}</td></tr>")
        parts.append("</table>")

    other = [f for f in verdict.findings if not (f.probe == "mutants" and f.code == "LINES_UNCHECKED")
             and not (f.probe == "claims" and f.code.startswith("CLAIM_"))]
    if other:
        parts.append("<h2>Findings</h2>")
        for f in sorted(other, key=lambda f: {ERROR: 0, WARN: 1, INFO: 2}[f.severity]):
            items = "".join(f"<li>{_e(i)}</li>" for i in f.items[:20])
            more = f"<li>… {len(f.items) - 20} more</li>" if len(f.items) > 20 else ""
            hint = f"<div class='hint'>→ {_e(f.hint)}</div>" if f.hint and f.severity != INFO else ""
            parts.append(f"<div class='f {f.severity}'><code>{_e(f.probe)} · {_e(f.code)}</code><div>{_e(f.message)}</div>"
                         f"{'<ul>' + items + more + '</ul>' if items else ''}{hint}</div>")
    ts = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    parts.append(f"<footer>bitecheck {_e(__version__)} · generated {ts} · execution evidence, no LLM judgement · "
                 "github.com/tejgokani/bitecheck</footer></main></body></html>")
    return "".join(parts)


def _file_block(plan: Plan, path: str, results: list[M.MutantResult]) -> str:
    data = git.read_head_file(plan.repo, plan.head, path) or b""
    lines = data.decode("utf-8", errors="replace").split("\n")
    changed = plan.code_lines.get(path, set())
    by_line: dict[int, list[M.MutantResult]] = {}
    for r in results:
        by_line.setdefault(r.mutant.line, []).append(r)
    show: set[int] = set()
    for ln in changed:
        show.update(range(max(1, ln - CONTEXT), min(len(lines), ln + CONTEXT) + 1))
    counted = [r for r in results if r.status in (M.KILLED, M.SURVIVED, M.TIMEOUT)]
    k = sum(1 for r in counted if r.status != M.SURVIVED)
    out = [f"<div class='file'><header><span>{_e(path)}</span><small>{k}/{len(counted)} caught · "
           f"{len(changed)} changed line(s)</small></header><div class='code'>"]
    prev = 0
    for ln in sorted(show):
        if prev and ln > prev + 1:
            out.append("<div class='gap'>⋯</div>")
        prev = ln
        rs = by_line.get(ln, [])
        cls = "row"
        if ln in changed:
            cls += " ch"
        if any(r.status == M.SURVIVED for r in rs):
            cls += " bad"
        elif any(r.status in (M.KILLED, M.TIMEOUT) for r in rs):
            cls += " good"
        text = lines[ln - 1] if ln - 1 < len(lines) else ""
        out.append(f"<div class='{cls}'><span class='n'>{ln}</span><pre>{_e(text)}</pre>")
        for r in rs:
            mark = {M.SURVIVED: "<span class='x'>✗ survived</span>", M.KILLED: "<span class='k'>✓ caught</span>",
                    M.TIMEOUT: "<span class='k'>✓ caught (hang)</span>"}.get(r.status, _e(r.status))
            by = f" by {_e(r.killed_by[0])}" if r.killed_by else ""
            out.append(f"<div class='mut'>{mark} {_e(r.mutant.describe())}{by}</div>")
        out.append("</div>")
    out.append("</div></div>")
    return "".join(out)
