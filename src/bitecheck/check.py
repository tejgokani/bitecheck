"""Run the selected probes over one change and assemble the verdict."""

from __future__ import annotations

import time

from .config import Config
from .core.runner import RunResult
from .evidence import ERROR, INFO, WARN, Finding, ProbeResult, Verdict
from .plan import Plan
from .probes import claims as claims_probe
from .probes import deps as deps_probe
from .probes import goalpost as goalpost_probe
from .probes import mutants as mutants_probe
from .probes import tamper as tamper_probe
from .transcripts import AgentMessage
from .workspace import Workspace


def run(plan: Plan, cfg: Config, *, probes: list[str], message: AgentMessage | None = None,
        online: bool = False, keep: bool = False, progress=None) -> tuple[Verdict, str | None]:
    say = progress or (lambda msg: None)
    results: list[ProbeResult] = []
    if not plan.changes:
        results.append(ProbeResult("plan", "ran", "no changes",
                                   [Finding("plan", "NO_CHANGES", INFO, "no differences between base and head")]))
        return Verdict(results, None, cfg.min_score), None

    if "tamper" in probes:
        results.append(tamper_probe.run(plan, cfg))
    if "deps" in probes:
        say("deps: checking new dependencies" + (" online" if online else ""))
        results.append(deps_probe.run(plan, online=online))

    needs_runs = any(p in probes for p in ("goalpost", "mutants", "claims"))
    workdir = None
    with Workspace(plan, cfg, keep=keep) as ws:
        if keep:
            workdir = str(ws.root)
        head_run: RunResult | None = None
        goal_codes: set[str] = set()
        if needs_runs:
            if not cfg.test_cmd:
                results.append(ProbeResult("runs", "error", "no test command",
                                           [Finding("runs", "NO_TEST_COMMAND", ERROR,
                                                    "no test command: pass --cmd or set test_cmd in .bitecheck.toml",
                                                    hint="configure a test command")]))
            else:
                say(f"running the test suite on the change: `{cfg.test_cmd}`")
                head_run = goalpost_probe.run_head(cfg, ws)
                say(f"  head: {'pass' if head_run.passed else 'FAIL'} in {head_run.duration:.1f}s")
        if "goalpost" in probes and head_run is not None:
            gp = goalpost_probe.run(plan, cfg, ws, progress, head_result=head_run)
            results.append(gp)
            goal_codes = {f.code for f in gp.findings}
            runs = gp.data or {}
            if "old_tests" in runs and runs["old_tests"].passed:
                goal_codes.add("goalpost:old_tests_pass")
        elif head_run is not None and not head_run.passed and head_run.exit_code is not None:
            results.append(ProbeResult("runs", "ran", "head fails", [Finding(
                "runs", "HEAD_FAILS", ERROR, "the test suite fails on the change itself",
                hint="make the full test suite pass before finishing")]))

        mrep = None
        if "mutants" in probes and head_run is not None:
            shared = head_run if cfg.effective_mutant_cmd == cfg.test_cmd else None
            mrep = mutants_probe.run(plan, cfg, ws, progress, baseline=shared)
            results.append(_mutation_result(plan, cfg, mrep))

        if "claims" in probes:
            score = mrep.score if mrep else None
            surv = len(mrep.survivors) if mrep else 0
            killed = sum(1 for r in mrep.counted if r.status != mutants_probe.SURVIVED) if mrep else 0
            results.append(claims_probe.run(plan, message, head=head_run, score=score, min_score=cfg.min_score,
                                            survivors=surv, killed=killed, goalpost_codes=goal_codes))
    score = None
    for r in results:
        if r.name == "mutants" and r.data is not None:
            score = r.data.score
    return Verdict(results, score, cfg.min_score), workdir


def _mutation_result(plan: Plan, cfg: Config, rep: mutants_probe.MutationReport) -> ProbeResult:
    f: list[Finding] = []
    name = "mutants"
    if rep.error:
        f.append(Finding(name, "MUTANTS_NOT_JUDGED", WARN, rep.error))
        return ProbeResult(name, "ran", "not judged", f, data=rep, elapsed=rep.elapsed)
    if plan.unsupported:
        f.append(Finding(name, "UNSUPPORTED_LANGUAGE", INFO, "changed code in languages bitecheck cannot mutate yet",
                         plan.unsupported))
    if rep.unloaded:
        f.append(Finding(name, "FILES_NOT_LOADED", WARN,
                         "changed files that no test loads: the suite still passes when they are deliberately "
                         "broken, so their lines were not judged", [f"{p}: {why}" for p, why in rep.unloaded.items()],
                         hint="add tests that import and exercise these files (or check for an editable install "
                              "or absolute path that bypasses the copy under test)"))
    if not rep.results:
        f.append(Finding(name, "NOTHING_TO_MUTATE", INFO, "no changed lines of supported code to mutate"))
        return ProbeResult(name, "ran", "nothing to mutate", f, data=rep, elapsed=rep.elapsed)
    counted = rep.counted
    killed = sum(1 for r in counted if r.status != mutants_probe.SURVIVED)
    score = rep.score
    if rep.survivors:
        sev = ERROR if score is not None and score < cfg.min_score else WARN
        items = [f"{r.mutant.path}:{r.mutant.line}  {r.mutant.describe()}" for r in rep.survivors]
        f.append(Finding(
            name, "LINES_UNCHECKED", sev,
            f"{len(rep.survivors)} changed line(s) can be broken without any test failing "
            f"({killed}/{len(counted)} caught, {score:.0%}; gate {cfg.min_score:.0%})",
            items, hint="for each line, add or strengthen a test assertion that fails when that line is wrong"))
    invalid = [r for r in rep.results if r.status == mutants_probe.INVALID]
    if invalid:
        f.append(Finding(name, "INVALID_MUTANTS", INFO, f"{len(invalid)} mutant(s) did not compile and were not counted"))
    skipped = [r for r in rep.results if r.status == mutants_probe.SKIPPED and r.note != "file not loaded by any test"]
    if skipped:
        f.append(Finding(name, "MUTANTS_SKIPPED", WARN, f"{len(skipped)} mutant(s) were not run (time budget)"))
    if rep.truncated:
        f.append(Finding(name, "MUTANTS_CAPPED", INFO, f"{rep.truncated} more mutant(s) exist beyond max_mutants "
                         f"({cfg.max_mutants}); run with --max-mutants 0 for all"))
    if score is not None:
        summary = f"{killed}/{len(counted)} caught ({score:.0%})"
    elif rep.unloaded:
        summary = "changed files are not loaded by any test"
    else:
        summary = "no countable mutants"
    return ProbeResult(name, "ran", summary, f, data=rep, elapsed=rep.elapsed)


__all__ = ["run", "time"]
