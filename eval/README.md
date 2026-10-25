# Agent evaluation

This directory measures one question: **does putting bitecheck in a coding agent's loop make the agent leave behind tests that catch real bugs?**

## Design

- **The independent metric.** Every task ships a correct `reference` implementation and hand-written buggy variants in `bugs/`. The agent's final test files are run against each variant.
  - A bug counts as *caught* when a test that passes on the reference fails on the bug.
  - Tests that fail on the reference are excluded rather than voiding the whole run. These are agent expectations that go beyond the spec.
  - bitecheck never sees these bugs, and they were written as realistic semantic mistakes, not as bitecheck operators.
- **The regression metric** (bug-fix tasks). `bugs/1_original_bug.*` is the code as it was before the fix. "Regression-protected" means the agent's final tests fail on it, i.e. the bug cannot silently come back.
- **The two arms are identical except for the hook.** Both get the same prompt, tools, model and `.bitecheck.toml`. Arm B adds a Claude Code `Stop` hook running `bitecheck hook`. Hook runs and blocks are recorded through `BITECHECK_HOOK_LOG`.
- **Implementation correctness** is checked with hidden tests (`hidden/`) the agent never sees.

## Task sets

| dir | kind | prompt |
|---|---|---|
| `tasks/` | 4 greenfield features | TASK.md asks for *thorough* tests |
| `tasks2/` | same features | "Add tests." (small model) |
| `tasks3/` | 4 bug fixes | issue text only; tests never mentioned |
| `tasks4/` | 6 new bug fixes, written after all product changes | issue text only |

## Reproduce

```bash
uv venv && uv pip install -e .            # the harness calls .venv/bin/bitecheck
python3 eval/run.py validate --tasks-dir eval/tasks4     # the benchmark checks itself
python3 eval/run.py run --tasks-dir eval/tasks4 --arms A,B --reps 2 --out eval/results/mine
python3 eval/run.py summarize eval/results/mine/results.json
```

You need the `claude` CLI logged in, plus `node` and `go` for the JS/Go tasks. Each agent run costs roughly $0.15–0.25 with the default model.

## Read the history

[PREREGISTRATION.md](PREREGISTRATION.md) records, in order:

- the expectations written before each run;
- a harness bug that made runs 1–2 invalid as hook comparisons;
- every product change, and which run motivated it.

Summary JSON for every run is in `results/`. Workspaces and raw agent logs are not committed.
