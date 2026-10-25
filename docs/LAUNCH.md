# Launch package

## Repository metadata

- **Description:** Your agent says the tests pass. Do they bite? bitecheck deliberately breaks every line your coding agent changed, re-runs your tests, and sends the agent back until its tests catch the breaks. Works with Claude Code, Codex, Gemini CLI, MCP and CI.
- **Topics:** `mutation-testing`, `coding-agents`, `claude-code`, `codex`, `gemini-cli`, `testing`, `code-review`, `ai-safety`, `developer-tools`, `mcp`

## Announcement draft (Show HN)

> **Show HN: bitecheck – make your coding agent prove its tests catch bugs before it can say "done"**
>
> Agents now write most of the diff *and* the tests that are supposed to verify it. A test can run a line without checking it, and coverage can't tell the difference. Mutation testing can: break the line, re-run the tests, and see if anything fails.
>
> Mutation testing has never fit into an agent's loop. Every language has its own tool, runs take hours, and the output is a dashboard rather than something an agent can act on. bitecheck is my attempt to fix that:
>
> - **Diff-scoped.** It only breaks the lines the agent changed, two different ways per line, in parallel copy-on-write snapshots. Cost scales with the diff, not the codebase.
> - **Language-neutral.** Use your own test command. Real lexers for 11 language families mean it never mutates strings, comments, regexes or generics. Mutants that don't compile are classified *invalid*, not "caught".
> - **Honest.** A canary run per file means files no test even loads are reported as "not loaded", never as fake survivors. That's a real problem with editable installs.
> - **In the loop.** One hook contract covers Claude Code `Stop`, Codex `Stop` and Gemini `AfterAgent`. When the agent tries to finish, bitecheck sends it back with the exact lines no test checks, at most 3 rounds.
> - **More than mutants.** It runs the old tests against the new code (moved goalposts), checks the agent's own claims ("comprehensive tests", "all tests pass") against what it re-executed, and flags `.only`, skips, `|| true`, and special-cased literals like `if year == 1900: return 29`.
>
> **What I measured** (see EVIDENCE in the README, with every run published, including the null results and a harness bug I caught): <fill from TEST_REPORT>
>
> No LLM, no network, zero dependencies, MIT. I'd love repos where it's wrong.

## The key design decision, in one paragraph

A survivor has to mean "no test checks this line". Everything in bitecheck serves that sentence:

- Strings and comments are never mutated.
- Non-compiling mutants are never counted as caught.
- Files no test loads are never counted as survivors.
- A config edited inside the change under review is never trusted.
- Each line gets two *different* kinds of breakage, because the happy path kills a negated `if` while the `raise` it guards goes untested.

## Demo script (terminal recording, about 45 seconds)

1. `examples/demo.sh`: a green suite, plus an agent message claiming comprehensive tests.
2. bitecheck's bar: "6 of 9 deliberately broken changed lines were caught".
3. The survivor list: `/` → `*` survived (the test only asserts `> 0`), and the member discount removed with nothing failing.
4. CLAIM_CONTRADICTED: "comprehensive tests".
5. `bitecheck install claude`, then rerun the same task in Claude Code. The Stop hook sends it back, the agent adds two assertions, and the next run passes.

## Where to share (relevant and permitted)

- Show HN
- r/ClaudeAI and r/ChatGPTCoding (tool posts are allowed; check the sidebar rules)
- The Claude Code hooks community lists
- A dev.to write-up: "Your agent's tests run the code. Do they check it?"
- An issue or discussion on mutation-testing projects (Stryker, mutmut, cargo-mutants), framed as an integration question, not an ad

## Good first issues

1. **Test impact selection.** Run only the test files that import the mutated module (Python `importlib` tracing; `node --test` file lists).
2. **Incremental cache.** Reuse mutant results keyed by (file hash, mutant id, test-file hashes) across hook rounds.
3. **End-to-end fixtures** for Rust (`cargo test`), TypeScript (vitest), Java (Maven) and Ruby (minitest).
4. **Windows support.** Process groups via `CREATE_NEW_PROCESS_GROUP`, and junctions instead of symlinks.
5. **More claim phrasings,** with negative examples (`probes/claims.py`).
6. **A `--watch` mode** for humans: re-verify on save.
7. **SARIF fixes:** suggested-test text attached to each survivor.
