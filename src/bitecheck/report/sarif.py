"""SARIF 2.1.0 output, so surviving mutants show up inline in GitHub code scanning."""

from __future__ import annotations

import json

from .. import __version__
from ..evidence import ERROR, WARN, Verdict
from ..plan import Plan
from ..probes import mutants as M

SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"

RULES = {
    "unchecked-line": ("A changed line can be broken without any test failing",
                       "bitecheck applied a small change (mutant) to this changed line and the full test suite "
                       "still passed. No test checks this line's behaviour."),
}


def render(plan: Plan, verdict: Verdict) -> str:
    results = []
    rules: dict[str, dict] = {}

    def rule(rid: str, short: str, full: str) -> None:
        rules.setdefault(rid, {"id": rid, "name": rid, "shortDescription": {"text": short},
                               "fullDescription": {"text": full},
                               "helpUri": "https://github.com/tejgokani/bitecheck#findings"})

    for p in verdict.probes:
        if p.name == "mutants" and isinstance(p.data, M.MutationReport):
            for r in p.data.survivors:
                m = r.mutant
                rule("unchecked-line", *RULES["unchecked-line"])
                results.append({
                    "ruleId": "unchecked-line", "level": "warning",
                    "message": {"text": f"Changing {m.describe()} did not make any test fail."},
                    "locations": [{"physicalLocation": {"artifactLocation": {"uri": m.path},
                                                        "region": {"startLine": m.line}}}],
                    "partialFingerprints": {"bitecheckMutant": f"{m.path}:{m.operator}:{m.original}"},
                })
        for f in p.findings:
            if f.severity not in (ERROR, WARN) or (p.name == "mutants" and f.code == "LINES_UNCHECKED"):
                continue
            rid = f"{f.probe}/{f.code.lower()}"
            rule(rid, f.message[:120], f.message)
            loc = None
            if f.items:
                # items look like "path:line: ..." for static findings
                head = f.items[0].split(":", 2)
                if len(head) >= 2 and head[1].isdigit():
                    loc = {"physicalLocation": {"artifactLocation": {"uri": head[0]},
                                                "region": {"startLine": int(head[1])}}}
            entry = {"ruleId": rid, "level": "error" if f.severity == ERROR else "warning",
                     "message": {"text": f.message + (f" ({'; '.join(f.items[:5])})" if f.items else "")}}
            if loc:
                entry["locations"] = [loc]
            results.append(entry)
    doc = {
        "$schema": SCHEMA,
        "version": "2.1.0",
        "runs": [{
            "tool": {"driver": {"name": "bitecheck", "version": __version__,
                                "informationUri": "https://github.com/tejgokani/bitecheck",
                                "rules": list(rules.values())}},
            "results": results,
            "properties": {"mutationScore": verdict.score, "minScore": verdict.min_score,
                           "base": plan.base, "head": plan.head},
        }],
    }
    return json.dumps(doc, indent=2)
