# Changelog

## 0.1.0 (unreleased)

First release.

- **Mutation probe.** Diff-scoped, language-neutral mutation testing with your own test command.
  - Lexers for Python, JS/TS, Go, Rust, Java, Kotlin, Swift, C/C++, C#, PHP and Ruby.
  - Ranked operators at one mutant per changed line.
  - Parallel copy-on-write workers.
  - Invalid mutants are separated from killed ones.
  - Per-file canary runs, so files no test loads are never reported as false survivors.
- **Goalpost probe** (from fliptest). Old tests on new code, and new tests on old code.
- **Tamper probe.** Skipped/focused tests, removed assertions, suppressions, swallowed errors, loosened
  gates and thresholds, rewritten snapshots, and special-cased test literals.
- **Deps probe.** Typosquat distance offline; registry existence and age with `--online`.
- **Claims probe.** Checks the agent's final message against bitecheck's own re-execution. Reads hook
  input, Claude Code and Codex transcripts.
- **Hook mode.** One adapter for Claude Code `Stop`, Codex `Stop` and Gemini `AfterAgent`, with round
  limits and a `BITECHECK_HOOK_LOG` audit trail.
- **Integrations.** `install claude|codex|gemini|all`, an MCP server, and a GitHub Action.
- **Reports.** Terminal, JSON, self-contained HTML, SARIF 2.1.0 and Markdown.
