# Pre-registration (written 2026-10-25, before any agent run)

**Question.** Does putting bitecheck in a coding agent's loop, as a Claude Code Stop hook, make the agent write tests that catch more real bugs?

**Design.**

- **Tasks:** 4 tasks: shipping (Python), password (Python), duration (JavaScript, `node --test`), backoff (Go).
- **Arms:**
  - A: Claude Code alone.
  - B: Claude Code with `bitecheck hook` as its Stop hook, `max_rounds = 3`.
- **What is held constant:** the prompt, the tools and the `.bitecheck.toml` file. The only difference between the arms is the hook. The prompt asks for thorough tests in both arms.
- **Primary metric:** held-out bugs caught, out of 5 per task. The agent's final test files are run against hand-written buggy reference implementations, and a bug counts as caught if a test fails on it. Tests that fail on the *correct* reference count as 0 for that task.
  - bitecheck never sees these bugs. Its operators are lexer-level single-token edits; the held-out bugs are semantic (dropped rules, wrong units, case-sensitivity, ordering).
- **Secondary metrics:** whether the implementation passes the hidden correctness tests, bitecheck's own mutation score, wall time, cost and hook rounds.

**Expectations.**

1. Arm B catches at least as many held-out bugs as arm A in total, and strictly more on at least 2 of the 4 tasks.
2. Arm B's implementation correctness is not worse than arm A's.
3. Arm B costs more time, roughly 1.5–3× per task.
4. Arm B's own bitecheck score is ≥ 0.8 on every task where the hook ran, or the agent explicitly argues that the survivors are equivalent.

**Honesty rules.** All results are reported, including ones that contradict these expectations. With 1–2 repetitions per cell this is an observation, not a statistically powered study, and it will be described that way.

---

# Run 2 pre-registration (written after run 1, before run 2)

**What run 1 showed.** With a prompt asking for *thorough* tests and the default Claude Code model, both arms wrote tests that scored 100% on bitecheck. The hook never had to block (0 rounds). Every valid test suite caught all held-out bugs, so this was a ceiling effect.

Run 1 also exposed two benchmark ambiguities. The agents tested out-of-spec inputs (`"²"` as a digit, `inf` weight) that my reference implementations handle differently. Scoring was therefore changed to the standard per-test rule, before looking at any arm comparison: a bug counts as caught when a test that passes on the reference fails on the bug.

**Run 2 changes two things, both toward ordinary use:**

1. **Task text.** TASK.md says "Add tests in `<file>`." instead of "Add thorough tests…". Nothing else changes.
2. **Model.** A smaller, cheaper model, `claude-haiku-5-5`, the kind many people run for routine agent work.

**Expectations.**

1. Arm A catches fewer held-out bugs than in run 1.
2. Arm B catches more held-out bugs than arm A in total.
3. The hook blocks at least once in arm B.
4. Implementation correctness is not worse in arm B.

If arm B doesn't beat arm A, that will be reported as-is.

---

# Run 3 pre-registration (written before run 3; run 2 was still finishing)

**What runs 1–2 suggested.** On greenfield "implement X and add tests" tasks, both the default model and a small model wrote tests that killed every one-per-line mutant, so the hook never needed to block. Asking for tests explicitly, on a small well-specified task, appears to be enough. This is not the situation where agents leave code unchecked.

**Run 3 tests the everyday case instead: bug fixes, where the prompt never mentions tests.**

**Design.**

- **Tasks:** 4 repos with existing passing tests that don't cover a bug: inventory reservation (Python), business days (Python), slugify (JavaScript), port parsing (Go).
- **Prompt:** "Fix this bug report: <issue text>. Run the tests with: <cmd>." Nothing about writing tests.
- **Arms:** A = no hook. B = `bitecheck hook` (product defaults: `per_line = 1`, `max_rounds = 3`). Default Claude Code model, 2 repetitions per cell.
- **Primary metric, regression protection:** does the final test suite fail when the *original* buggy file is restored? This is the question "would this bug come back unnoticed?".
- **Secondary metrics:** 3 held-out near-fix bug variants per task (off-by-one, wrong comparison, partial fix), scored per test against the reference; hidden correctness of the fix; time; cost; hook runs and blocks, read from `BITECHECK_HOOK_LOG`.

**Expectations.**

1. Arm A frequently fixes the bug without adding a regression test, so regression protection is clearly below 100%.
2. Arm B reaches regression protection in more runs than arm A, because the fix's changed lines survive mutation until a test checks them.
3. Arm B blocks at least once.
4. Fix correctness is equal across arms.

---

# Correction (written after run 2, before run 3)

**What went wrong.** A harness bug meant **arm B never had the hook installed in runs 1 and 2.** `prepare()` received arm labels like `"B0"` but checked `arm == "B"`. The bug was found because run 2's hook audit log (`BITECHECK_HOOK_LOG`) was empty.

**How runs 1–2 are reinterpreted.** Both arms ran the agent *without* bitecheck. They are reported as no-hook baselines, 12 tasks × 2 samples. They say nothing about the hook's effect.

**What was fixed.** The harness now checks `arm.startswith("B")`. Before any further runs, it is smoke-tested by confirming the audit log is non-empty for an arm-B run.

---

# Disclosure: product change before run 3

**What the smoke run showed.** A single smoke run of the fixed harness used the run-3 task `reserve`. The hook ran and passed an agent fix that had **no regression test**. Two mutation weaknesses caused this:

- No operator removed a `raise`/`throw`.
- One mutant per line chose condition negation, which the happy-path test kills.

**What changed before run 3, without looking at the other three tasks:**

1. Error-path operators were added: remove `raise`/`throw`, Go `return x, err` → `return x, nil`, and Ruby `raise` → `nil`. These are standard in mainstream mutation tools.
2. The default `per_line` changed from 1 to 2, preferring two *different* operators per line.

**Caveat.** Both changes were motivated by a run-3 task, so `reserve` results are reported with that caveat. `bizdays`, `slug` and `port` had not been run by any agent before these changes.

---

# Run 4 pre-registration: out-of-sample (written before any agent or bitecheck run on these tasks)

**Run 3 results** (bitecheck commit with error-path operators). Arm A: regression-protected 2/8, held-out 10/32. Arm B: 4/8, 17/32. Where the hook blocked (port, reserve), the agent added a regression test in 4 of 4 runs. Where it didn't block, there were two product gaps:

- **bizdays:** the two per-line picks were the same kind of breakage (negation twice).
- **slug:** the fix lived entirely in a regex literal, which nothing mutated.

Both were fixed with operator families and regex operators. Because those fixes were motivated by run-3 tasks, run 3 can't validate them. Run 4 can.

**Design.**

- **Tasks:** 6 new bug-fix tasks written after those fixes, never run by any agent and never checked with bitecheck: paginate (Python), merge (Python, recursion), bytes (JavaScript), query (JavaScript, parsing), truncate (Go, Unicode), median (Go).
- **Everything else unchanged from run 3:** the issue-only prompt with no mention of tests, the default model, 2 repetitions, arm A vs arm B, and the same metrics.

**Expectations.**

1. Arm B is regression-protected in more runs than arm A.
2. Arm B catches more held-out bugs in total.
3. Fix correctness is the same in both arms (±1 run).
4. Arm B's median wall time is under 3× arm A's.

## Run 4 results (filled in after the run, nothing altered above)

- **Arm A:** regression-protected 5/12; held-out 18/48 (38%); correctness 12/12; median 18s; total $1.94.
- **Arm B:** regression-protected **12/12**; held-out **44/48 (92%)**; correctness 12/12; median 37s; total $2.29. The hook blocked 8 times, always once per run.

All four expectations held. Where B did not improve (`bytes`), its mutation score of 88% cleared the 0.8 gate, so the hook never blocked.

---

# Run 2b (written before running)

**Why.** Runs 1–2 never tested arm B because of the harness bug. This reruns **arm B only** for the run-2 setup (greenfield tasks, "Add tests.", `claude-haiku-5-5`, 2 repetitions) and compares against the existing run-2 arm-A data.

**Expectation.** No meaningful difference. Arm A already caught 40/40 held-out bugs, a ceiling. This mainly checks that the hook does not make greenfield work worse or much slower.
