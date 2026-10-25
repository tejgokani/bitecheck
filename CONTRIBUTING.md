# Contributing

The most valuable contributions, in order:

1. **A repo where bitecheck is wrong.** This means a survivor that is really an equivalent mutant, a mutant
   inside a string or comment, a missed red flag, or a test runner that misbehaves in a snapshot. A script
   that builds the repo (like `examples/demo.sh`) makes it fixable.
2. **Lexer and operator fixes for a language.** `src/bitecheck/lang/`. Every fix needs a case in
   `tests/test_lang.py`.
3. **Runner recipes** (JUnit flags, fail-fast flags) for the README.
4. **New agent integrations.** Any agent with a stop/after-turn hook that accepts "exit 2 + stderr" works
   already. See `integrations/install.py`.

## Development

```bash
uv venv && uv pip install -e . pytest ruff
.venv/bin/python -m pytest -q          # ~100 end-to-end tests; real git repos, real pytest/node/go runs
.venv/bin/ruff check src tests
python3 eval/run.py validate           # the agent-evaluation benchmark checks itself
```

The JS and Go tests are skipped when `node` or `go` is not installed.

## Ground rules

- **No runtime dependencies.** The standard library is enough.
- **Never modify the user's repository.** Changes to `core/` or `workspace.py` must keep
  `test_repo_is_byte_identical_after_run` passing.
- **Never mutate inside strings or comments.** Lexer changes need adversarial test cases.
- **A survivor must mean "no test checks this".** If you add an operator, show that it rarely produces
  equivalent mutants.
- Be kind; see [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
