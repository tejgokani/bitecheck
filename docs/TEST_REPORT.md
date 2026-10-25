# Test report

Date: 2026-10-25. Machine: macOS arm64. Everything listed as "verified" was actually executed. Hosted CI status is on the repository's Actions page.

## Automated suite

```
.venv/bin/python -m pytest -q        # Python 3.11
102 passed
.venv/bin/ruff check src tests
All checks passed!
```

There are no mocks, apart from one monkeypatched registry lookup. The tests create real git repositories and run the real CLI, with real pytest, `node --test` and `go test` inside the snapshots.

| Area | What is covered |
|---|---|
| Lexers/operators (`test_lang.py`) | Strings, comments, template literals, raw strings, regex literals, Rust lifetimes, C# verbatim strings and Ruby `=begin` blocks are never mutated; Python mutants all parse; generics, unary operators and macros are left alone; error-path, regex and family-distinct operators |
| Mutation e2e (`test_mutation.py`) | Weak vs strong tests; only changed lines are mutated; repo byte-identical afterwards (bytes, mtimes, index, status, worktrees); CRLF preserved; an infinite-loop mutant counts as a timeout kill; baseline failure; caps; exclude globs; unsupported languages; SIGINT kills workers and cleans up; JavaScript; Go with non-compiling (invalid) mutants; canary for unloaded files; editable-install safety |
| Probes (`test_probes.py`) | Goalpost; 10 tamper rules; special-case detection and its false-positive guard; typosquats (npm and PyPI); manifest parsers; online missing-package path; 9 claim-extraction cases; claims checked end to end; transcript and session auto-discovery |
| Integrations (`test_integrations.py`) | Hook contracts for Claude Code, Codex and Gemini; round limits; verified-change cache; no blocking on config errors; non-blocking feedback; installer (idempotent, merge, backup, uninstall, refuses broken JSON); MCP server JSON-RPC; HTML/SARIF/Markdown reports (escaping, self-contained); CLI usage errors; config read from the base revision |

## Agent evaluation

See [`eval/PREREGISTRATION.md`](../eval/PREREGISTRATION.md), the full chronological record. In summary:

- **Run 4** (out-of-sample, 6 new bug-fix tasks, 12 runs per arm):
  - Regression-protected fixes went from 5/12 to **12/12**.
  - Held-out bugs caught went from 38% to **92%**.
  - Correctness was 12/12 in both arms.
  - Median time went from 18s to 37s, and cost rose 18%.
- **Run 3:** 2/8 → 4/8. The two failures exposed two product gaps, since fixed.
- **Runs 1–2:** invalid as hook comparisons because of a harness bug. They are reported as no-hook baselines.
- **Run 2b:** aborted with no data (usage limit).

## Not verified

- **Languages run end to end:** only Python, JavaScript and Go. TypeScript, Rust, Java, Kotlin, Swift, C/C++, C#, PHP and Ruby have unit-tested lexers only.
- **Real open-source commits:** not yet run, so the equivalent-mutant rate is not measured.
- **Agents:** Codex and Gemini hooks are tested against their documented contracts with simulated payloads, not with the real CLIs. Claude Code was tested for real.
- **Platforms:** Windows is not supported.
