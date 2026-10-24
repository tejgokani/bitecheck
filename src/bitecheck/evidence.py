"""The shared evidence model every probe reports into."""

from __future__ import annotations

from dataclasses import dataclass, field

ERROR, WARN, INFO = "error", "warn", "info"
_RANK = {ERROR: 2, WARN: 1, INFO: 0}


@dataclass
class Finding:
    probe: str
    code: str
    severity: str
    message: str
    items: list[str] = field(default_factory=list)
    path: str | None = None
    line: int | None = None
    hint: str | None = None  # what an agent (or human) should do about it


@dataclass
class ProbeResult:
    name: str
    status: str  # ran | skipped | error
    summary: str = ""
    findings: list[Finding] = field(default_factory=list)
    data: object = None
    elapsed: float = 0.0

    @property
    def worst(self) -> str:
        if not self.findings:
            return "ok"
        w = max(self.findings, key=lambda f: _RANK[f.severity]).severity
        return "ok" if w == INFO else w


@dataclass
class Verdict:
    probes: list[ProbeResult]
    score: float | None  # mutation score on changed lines, if measured
    min_score: float

    @property
    def findings(self) -> list[Finding]:
        return [f for p in self.probes for f in p.findings]

    @property
    def worst(self) -> str:
        sev = {f.severity for f in self.findings}
        return ERROR if ERROR in sev else WARN if WARN in sev else "ok"

    def failed(self, strict: bool = False) -> bool:
        return self.worst == ERROR or (strict and self.worst == WARN)
