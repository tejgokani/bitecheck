"""Machine-readable report (schema 1)."""

from __future__ import annotations

import json

from .. import __version__
from ..core.runner import RunResult
from ..evidence import Verdict
from ..plan import Plan
from ..probes import claims as C
from ..probes import mutants as M

SCHEMA = 1


def _run(r: RunResult | None):
    if r is None:
        return None
    return {"exit_code": r.exit_code, "passed": r.passed, "timed_out": r.timed_out,
            "duration_s": round(r.duration, 3), "tests": r.tests}


def to_dict(plan: Plan, verdict: Verdict, cmd: str) -> dict:
    probes = []
    for p in verdict.probes:
        d = {"name": p.name, "status": p.status, "summary": p.summary, "worst": p.worst,
             "elapsed_s": round(p.elapsed, 3),
             "findings": [{"code": f.code, "severity": f.severity, "message": f.message, "items": f.items,
                           "path": f.path, "line": f.line, "hint": f.hint} for f in p.findings]}
        if isinstance(p.data, M.MutationReport):
            rep = p.data
            d["mutation"] = {
                "score": rep.score, "jobs": rep.jobs, "truncated": rep.truncated, "error": rep.error,
                "baseline": _run(rep.baseline),
                "files": {k: vars(v) for k, v in rep.files.items()},
                "mutants": [{"path": r.mutant.path, "line": r.mutant.line, "operator": r.mutant.operator,
                             "original": r.mutant.original, "replacement": r.mutant.replacement,
                             "status": r.status, "duration_s": round(r.duration, 3), "killed_by": r.killed_by,
                             "note": r.note} for r in rep.results],
            }
        elif isinstance(p.data, dict) and p.name == "goalpost":
            d["runs"] = {k: _run(v) for k, v in p.data.items()}
        elif isinstance(p.data, dict) and p.name == "claims":
            d["agent"] = p.data.get("agent")
            d["claims"] = [{"kind": c.kind, "quote": c.quote, "verdict": c.verdict, "evidence": c.evidence}
                           for c in p.data.get("claims", []) if isinstance(c, C.Claim)]
        probes.append(d)
    return {
        "schema": SCHEMA,
        "tool": {"name": "bitecheck", "version": __version__},
        "verdict": verdict.worst,
        "score": verdict.score,
        "min_score": verdict.min_score,
        "base": plan.base,
        "head": plan.head,
        "test_cmd": cmd,
        "changes": {"code": [c.path for c in plan.code_changes], "tests": [c.path for c in plan.test_changes],
                    "changed_code_lines": plan.changed_code_line_count},
        "probes": probes,
    }


def render(plan: Plan, verdict: Verdict, cmd: str) -> str:
    return json.dumps(to_dict(plan, verdict, cmd), indent=2)
