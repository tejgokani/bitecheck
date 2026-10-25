<div align="center">

# bitecheck

**Your agent says the tests pass. Do they actually bite?**

bitecheck verifies AI-written code with *execution evidence*, not opinions.
It deliberately breaks every line your agent changed, re-runs your tests, and shows you which breaks no test notices.
Then it hands those findings back to the agent, so the agent has to fix its tests before it's allowed to finish.

[![ci](https://github.com/tejgokani/bitecheck/actions/workflows/ci.yml/badge.svg)](https://github.com/tejgokani/bitecheck/actions/workflows/ci.yml)
![python](https://img.shields.io/badge/python-3.11%2B-blue) ![deps](https://img.shields.io/badge/runtime%20deps-0-brightgreen) ![license](https://img.shields.io/badge/license-MIT-green)

Works with **Claude Code · Codex · Gemini CLI · any MCP agent · GitHub Actions**. It runs locally, offline and without an LLM, on Python, JS/TS, Go, Rust, Java, Kotlin, Swift, C/C++, C#, PHP and Ruby.

</div>

```
$ git diff --stat
 cart.py      | 11 +++++++++++
 test_cart.py | 11 +++++++++++

$ pytest -q
3 passed in 0.00s

agent: "Added total() with coupon and member discounts. I added comprehensive tests and all tests pass."

$ bitecheck
  ██████████████████░░░░░░  6 of 8 deliberately broken changed lines were caught  (75%, gate 80%)

  ✗ cart.py:8   `/` → `*`               survived: no test failed
  ✗ cart.py:12  `amount *= 0.95` → `pass`  survived: no test failed

  ● goalpost  head pass · base pass · old_tests pass · new_tests FAIL
  ● mutants   6/8 caught (75%)
  ● claims    3 claim(s): 1 contradicted
      ERROR CLAIM_CONTRADICTED: the agent claimed the tests are thorough, but only 6 of 8
            deliberately broken changed lines were caught by the tests (75%)
  verdict: FAIL
```

That's real output from [`examples/demo.sh`](examples/demo.sh), trimmed. The suite was green and coverage would say 100%. But halving a price is never checked (the test asserts `> 0`), and the member discount could be deleted without a single test noticing.

---

## Why this exists

**Verification is the bottleneck now.**
- **AI writes the code.** Sonar's 2026 State of Code survey reports that 42% of committed code is AI-generated, and that 96% of developers don't fully trust it.
- **Review is the bottleneck.** Qodo's 2026 report names reviewing AI code as teams' top bottleneck.

**Green tests are the evidence everyone leans on, and agents write those tests too.** A test can *execute* a line without *checking* it. Coverage can't tell the difference. Mutation testing can: if you break the line and nothing fails, nothing checks it.

**Mutation testing has never been something agents could use in the loop.**
- It's set up separately per language: Stryker, mutmut, PIT, cargo-mutants.
- It usually runs on the whole codebase, which is far too slow for a feedback loop.
- No existing tool sends its results back to the agent as a "you're not done" signal.
- Trail of Bits' [*Mutation testing for the agentic era*](https://blog.trailofbits.com/2026/04/01/mutation-testing-for-the-agentic-era/) names performance as the biggest obstacle. On mutation-driven test generation, their answer is "stay tuned".

bitecheck closes that loop:

```
   agent edits code ──► agent says "done" ──► Stop hook ──► bitecheck
         ▲                                                    │  breaks each changed line,
         │                                                    │  re-runs your tests,
         │   "cart.py:12 `amount *= 0.95` → `pass` survived:  │  checks the agent's claims
         │    no test checks the member discount. Add an      │
         └──── assertion. Do not skip or weaken tests."  ◄────┘  (max 3 rounds, then it lets go)
```

## What it checks

| Probe | Question | How |
|---|---|---|
| **mutants** | Do the tests notice when the *changed* code is wrong? | Breaks each changed line once with the strongest applicable operator, runs your test command in an isolated copy-on-write worker, and reports which breaks survive |
| **goalpost** | Did the change only pass because the tests changed? | Runs the **old** tests on the **new** code, and the **new** tests on the **old** code ([fliptest](https://github.com/tejgokani/fliptest)) |
| **claims** | Is what the agent *said* true? | Extracts "all tests pass", "added comprehensive tests", "no behaviour change", "didn't touch the tests"… and checks each against bitecheck's own re-execution |
| **tamper** | Did it take shortcuts? | `.only`/skip markers, deleted assertions, `# type: ignore`/`eslint-disable`, swallowed exceptions, `\|\| true`, lowered coverage thresholds, rewritten snapshots, and `if year == 1900: return 29`-style special-casing of test literals |
| **deps** | Did it add a hallucinated package? | Typosquat distance to popular npm/PyPI/crates names offline; with `--online`, checks that the package exists and how old it is (slopsquatting) |

Every finding comes with evidence and a concrete fix. `bitecheck explain <CODE>` describes each one.

## Evidence

I ran a pre-registered A/B experiment with Claude Code on **6 brand-new bug-fix tasks** (Python, JavaScript, Go). The tasks were written after the last change to bitecheck, and no agent had seen them. The prompt was just the bug report, with no mention of tests. Arm A is Claude Code alone. Arm B is Claude Code with `bitecheck install claude`. Everything else was identical.

| 12 runs per arm | Claude Code alone | + bitecheck hook |
|---|---|---|
| **Bug fixes protected by a regression test**<br><sub>the final tests fail if the original bug comes back</sub> | 5 / 12 | **12 / 12** |
| **Held-out bugs caught**<br><sub>hand-written buggy variants bitecheck never saw, run against the agent's final tests</sub> | 18 / 48 (38%) | **44 / 48 (92%)** |
| Fix correct (hidden tests) | 12 / 12 | 12 / 12 |
| Median time · total cost | 18 s · $1.94 | 37 s · $2.29 |

- **The loop is short.** The hook sent the agent back 8 times, always for a single round. Each time it named the changed lines no test checked: an untested `raise` (paginate), `and` → `or` in the recursion guard (merge), the even-length average (median), the `<=` boundary (truncate). Each time, the agent added the missing tests.
- **One task didn't improve.** On `bytes`, the agent's tests already caught 88% of mutants, which cleared the 80% gate. The hook didn't push, and both arms missed the same 2 held-out bugs.

**What this does *not* show.**

- n = 2 runs per task per arm, one model, and small tasks I wrote. It's an observation, not a powered study.
- On greenfield "implement X and add thorough tests" tasks, Claude already wrote strong tests without help (40/40 held-out bugs caught), so there was nothing for bitecheck to add.

**The full record** is in [`eval/PREREGISTRATION.md`](eval/PREREGISTRATION.md): expectations written before each run, a harness bug that invalidated two early runs, two product gaps that runs exposed (and their fixes), and the null results. You can reproduce it with [`eval/`](eval/README.md).

## Install

```bash
pipx install git+https://github.com/tejgokani/bitecheck      # or: uv tool install git+https://github.com/tejgokani/bitecheck
```

Requires Python ≥ 3.11 and git. It has no runtime dependencies. It isn't on PyPI yet.

## Quick start

From any git repo with uncommitted changes:

```bash
bitecheck plan                 # which changed lines would be checked; runs nothing
bitecheck                      # check the working tree against HEAD (test command auto-detected)
bitecheck --cmd "npm test" --html report.html
bitecheck --base origin/main --head HEAD     # a branch or PR
```

### Put it in your agent's loop

```bash
bitecheck install claude    # .claude/settings.json  → Stop hook
bitecheck install codex     # .codex/hooks.json      → Stop hook (trust it once with /hooks)
bitecheck install gemini    # .gemini/settings.json  → AfterAgent hook
bitecheck install all --global   # in your home config instead of this repo
```

All three agents share one contract: exit code 2 plus feedback on stderr makes the agent keep working. bitecheck uses it to send the agent back with the evidence, at most `max_rounds` times per user turn (default 3), so it can never loop forever. Installs merge into existing settings, are idempotent, make a backup, and are reversed with `--uninstall`.

Any **MCP** agent can also verify itself mid-task:

```json
{ "mcpServers": { "bitecheck": { "command": "bitecheck", "args": ["mcp"] } } }
```

It provides `bitecheck_verify` and `bitecheck_plan`.

### In CI

```yaml
permissions: { contents: read, security-events: write }
steps:
  - uses: actions/checkout@v4
    with: { fetch-depth: 0 }
  - uses: tejgokani/bitecheck@main
    with:
      test-command: pytest -q
      min-score: "0.8"
```

This writes a job summary, uploads SARIF so unchecked lines show up inline in the PR, and attaches the HTML report.

## How the mutation engine works

- **Diff-scoped.** Only lines the change added or modified are mutated. The cost scales with the size of the diff, not the codebase.
- **Two different kinds of breakage per line by default.** Operators are ranked by how rarely they produce equivalent mutants:
  1. Remove a call statement.
  2. Remove a `raise`/`throw`, or drop a Go `err` return.
  3. `return x` → `return None`.
  4. Negate a condition.
  5. Swap `&&`/`||`.
  6. Flip a comparison.
  7. Swap arithmetic.
  8. Flip a boolean.
  9. Change a constant.
  10. Move a boundary.

  Each line gets its two strongest *distinct* operators. A negated `if` alone is often killed by the happy path; pairing it with a boundary or error-path mutant checks what the change was for. `--per-line 1` is cheaper; `--per-line 0` runs every operator.
- **Lexers that know what isn't code.** Strings, template literals with nested `${}`, raw strings (`r#"…"#`, Go backticks, C# `@"…"`), triple-quoted strings, comments, JS regex literals, Rust lifetimes vs char literals and Ruby symbols are never mutated. Generics (`Map<string, Array<number>>`), unary operators, pointer derefs, Rust macros, string concatenation, `%` formatting and logging lines are left alone.
- **Invalid ≠ killed.** A mutant that doesn't compile proves nothing about your tests:
  - Python mutants are pre-checked with `compile()`.
  - Elsewhere, compiler-error signatures (and an optional `check_cmd` such as `go vet ./...` or `tsc --noEmit`) mark them *invalid*, and they're excluded from the score.
- **Canaries.** Before trusting survivors, bitecheck breaks each changed file outright. If the suite still passes, no test loads that file (or an editable install bypasses the copy under test). Its mutants are marked *not judged*, never reported as false survivors.
- **Isolation and speed.** Workers run in parallel on APFS clones or reflinks of a snapshot. Mutant runs use a fail-fast variant of your command (`pytest -x`, `go test -failfast`), and timeouts adapt to your suite. A hanging mutant counts as caught.

## Configuration

Commit a `.bitecheck.toml`. **It's read from the base revision**, so a change can't loosen its own gate.

```toml
test_cmd = "pytest -q"
mutant_cmd = "pytest -q -x"      # default: fail-fast variant of test_cmd
check_cmd = ""                   # e.g. "go vet ./..." or "npx tsc --noEmit" to classify non-compiling mutants
junit = "report.xml"             # optional per-test detail
min_score = 0.8                  # gate: share of deliberately broken changed lines the tests must catch
max_mutants = 80                 # 0 = no cap
per_line = 2                     # distinct operators per changed line; 0 = every operator
jobs = 0                         # 0 = auto
budget = 0                       # seconds for the mutation phase; 0 = unlimited
probes = ["mutants", "goalpost", "claims", "tamper", "deps"]
exclude = ["migrations/**", "**/generated/**"]
max_rounds = 3                   # hook mode: times to send the agent back per turn
```

To exclude a line, add `# bitecheck: ignore` (or `// bitecheck: ignore`). If that pragma is added in the same change under review, the tamper probe reports it.

## Output

The terminal output is colored and respects `NO_COLOR`. Other formats:

| Flag | Output |
|---|---|
| `--json` | Machine-readable output, schema 1 |
| `--html FILE` | A self-contained report with an annotated diff, claims table and findings. No external requests; works offline |
| `--sarif FILE` | SARIF 2.1.0, for GitHub code scanning |
| `--markdown FILE` | Markdown, for PR comments and job summaries |
| `--feedback` | The text an agent receives |

Exit codes:

| Code | Meaning |
|---|---|
| `0` | Verified (warnings allowed unless `--strict`) |
| `1` | Findings |
| `2` | Usage or config error. In hook mode, 2 means "agent, keep working" |
| `130` | Interrupted |

## Safety

bitecheck runs your test command, in copies of your repo. That's the same trust level as running your tests.
- Your checkout, index, refs and worktrees are never modified.
- Child processes are killed on timeout or interrupt.
- No network access unless you pass `--online`.

Details are in [SECURITY.md](SECURITY.md).

## Limitations (read these)

- **Cost scales with your suite.** Each changed line costs about one test run (fail-fast), plus one canary per changed file, plus 2–4 suite runs for goalpost. Use `mutant_cmd` to target fast tests, `max_mutants`/`budget` to cap, and `--probes` to choose.
- **Equivalent mutants exist.** A change that can't alter behaviour will survive. bitecheck ranks operators to minimise this, but you'll sometimes need to judge, and the agent feedback says so explicitly.
- **Lexer-level, not type-aware.** Some mutants don't compile in typed languages. They're classified *invalid* by compiler output or `check_cmd`, never counted as caught.
- **Shared dependencies.** `node_modules`/`.venv` are symlinked from your checkout, so monorepo workspace links that point back into your checkout bypass the snapshot. The canary catches this, and reports those files as not loaded instead of guessing.
- **It verifies tests, not intent.** Strong tests of the wrong behaviour still pass. Claim checking is rule-based, so it recognises common phrasings, not arbitrary prose.
- **Verified end to end on Python (pytest), JavaScript (`node --test`) and Go (`go test`).** The lexers and operators for TypeScript, Rust, Java, Kotlin, Swift, C/C++, C#, PHP and Ruby are unit-tested, but haven't yet been run end to end against real projects. Reports are welcome.
- **POSIX only** (macOS and Linux). Windows isn't supported yet.

## Roadmap

- Test impact selection (run only the tests that load the mutated file) for large suites
- Incremental cache keyed by file hash, so unchanged mutants aren't re-run between hook rounds
- Type-aware operators via optional tree-sitter
- Codex and Gemini end-to-end evaluations alongside the Claude Code one
- A PyPI release and a Homebrew formula

## Contributing

The most useful bug report is a repo where bitecheck is wrong. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE). The bundled npm popularity list is from [npm-high-impact](https://github.com/wooorm/npm-high-impact) (MIT; see `src/bitecheck/data/NOTICE-npm-high-impact.txt`).
