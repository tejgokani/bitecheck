# Product thesis and architecture

## Thesis

**bitecheck: do your agent's tests actually bite?**

It is an execution-evidence verifier for code changes, built for the era when agents write most of the diff. It runs on your machine and needs no LLM.

- **Target user:** anyone who merges agent-written code, from a solo developer running Claude Code or Codex to a team reviewing agent PRs in CI.
- **The failure today:**
  1. The agent says "done, all tests pass, added comprehensive tests."
  2. A human skims a 400-line diff.
  3. Green CI is taken as proof.
  4. Nobody checks whether the new tests would notice if the new code were wrong.
- **The workflow bitecheck enables:**
  1. The agent finishes.
  2. bitecheck mutates the lines the agent changed, runs your test command, and finds the lines no test checks.
  3. It also checks whether old tests were edited to pass, and whether the agent's claims hold up.
  4. The surviving mutants go back to the agent as concrete, actionable failures ("`total *= rate` → `total /= rate` survived: nothing asserts the discounted total").
  5. The agent fixes its tests, and the loop repeats until the evidence clears the bar.
- **Core technical contribution:** a language-neutral, diff-scoped mutation engine that works with *your* test command. It uses lexer-level operators for Python, JS/TS, Go, Rust, Java, C/C++, C#, Kotlin, Swift, PHP and Ruby, runs parallel copy-on-write workers, and separates "invalid mutant" from "killed".
  - It sits inside an agent-agnostic enforcement loop: one hook contract for Claude Code `Stop`, Codex `Stop` and Gemini `AfterAgent`.
  - Around it are cross-checking probes (goalpost, claims, tamper, dependencies), all reported as evidence.
- **What it will not do:** use an LLM to judge code, upload anything, generate tests itself (the agent does that; bitecheck grades it), or replace a full mutation campaign tool for whole-codebase audits.
- **Smallest proof:** an agent writes a feature plus tests and claims "comprehensive tests". bitecheck shows that 2 of 9 changed lines are checked. With the hook on, the agent iterates, and the next run shows 9 of 9.

## Acceptance criteria

1. Install with `pipx install` / `uvx` with zero runtime dependencies, then `bitecheck` runs in a repo with uncommitted changes.
2. Generate mutants only on changed, non-test, supported-language lines, never inside strings or comments.
3. Report a correct killed/survived/timeout/invalid status on Python, JS and Go fixture repos.
4. Mutation never touches the user's repo, even under SIGINT/SIGTERM or timeouts. Workers are isolated.
5. Hook mode works with the documented contracts of Claude Code, Codex and Gemini. Round limiting must make loops impossible.
6. Goalpost, claims, tamper and dependency probes each have scenario tests.
7. Produce valid text, JSON, Markdown, SARIF 2.1.0 (validated against the schema's required fields), and self-contained HTML.
8. Run a real agent loop and measure the change in mutation score with and without the hook, with expectations written down before running.
9. Run on real OSS commits in at least two languages, and hand-triage the survivors for equivalent mutants.
10. CI goes green on Linux and macOS.

## Architecture

```
            ┌────────────── cli.py ───────────────┐
 hook stdin │  check · mutants · goalpost · claims │  install claude|codex|gemini · mcp
            └───────┬──────────────────────────────┘
                    │ Plan (diff → changed lines, tests vs code, language)
        ┌───────────┼───────────────┬──────────────┬────────────┐
   probes/mutants  probes/goalpost probes/claims  probes/tamper probes/deps
        │               │               │
   lang/lexer ──► lang/operators        transcripts (claude/codex/gemini)
        │
   core/snapshot (private-index materialise, CoW clone) · core/runner (process groups, timeouts)
                    │
               Evidence (findings + per-line results)
                    │
   report/ text · json · markdown · sarif · html        integrations/ hook · install · mcp · action.yml
```

## Key decisions

- **Python, stdlib only.** The cost is dominated by test runs, not by the orchestrator. Zero dependencies means `uvx bitecheck` works anywhere, and Python 3.11 brings `tomllib`.
- **Lexer-level operators, not tree-sitter.** Tree-sitter would add a native dependency and grammar packaging per language. The universalmutator paper ("Syntax Is All You Need", FSE '24) shows that syntax-light mutation captures most useful mutants. bitecheck adds a real lexer per language family, so strings, comments, template literals, raw strings and char/lifetime literals are never mutated. Python gets the stdlib `tokenize` module plus `ast` for statement-level mutants.
- **Invalid vs killed.** A mutant that fails to compile proves nothing about the tests. Python mutants are pre-checked with `compile()`. Other languages use an optional `check_cmd` (e.g. `go vet`, `tsc --noEmit`, `cargo check`) plus compiler-error signatures in the output. Invalid mutants are excluded from the score.
- **One mutant per changed line by default,** picked by operator priority. This follows Google's code-review mutation practice (Petrović et al.). It keeps cost linear in the diff size, which matters inside an agent loop. `--per-line N` and `--all` expand it.
- **Copy-on-write workers.** Each worker gets an APFS `clonefile` (`cp -c`) or Linux `--reflink=auto` copy of the head snapshot, falling back to a plain copy. Mutants are applied in place in the worker's copy and restored after each run.
- **Config is read from the base revision.** The change under review must not be able to grade itself (carried over from fliptest).
- **One hook contract.** Exit 2 + stderr works on Claude Code, Codex and Gemini. Rounds are tracked per `session_id` in the temp dir, and `stop_hook_active` plus `max_rounds` make infinite loops impossible.
- **Claims come from the agent's own words.** Hook stdin carries the final message on Codex and Gemini, and Claude Code exposes it through `transcript_path`. Rule-based extraction stays deterministic and offline. Every claim is checked against bitecheck's own re-execution, never against the agent's recorded commands.
