# Security policy

## Threat model

bitecheck runs **your test command** many times, inside temporary copies of **your** repository. Mutating
code and running the tests is exactly as trusted as running that repository's tests yourself. Do not run
bitecheck on code whose tests you would not run.

### What bitecheck guards against

- **The change grading itself.** `.bitecheck.toml` (test command, gate, probes) is read from the *base*
  revision, so a change cannot set `min_score = 0` or `test_cmd = "true"`. Editing it is reported as
  `CONFIG_EDITED`. Ignore pragmas added in the same change are reported as `CHECKS_SUPPRESSED`.
- **Damage to your checkout.** bitecheck writes no index, ref, worktree or stash, and never touches a file
  in your checkout. Snapshots are built with a private `GIT_INDEX_FILE`, and every mutant is applied inside
  a disposable copy. The test suite checks byte identity, mtimes, index, status and worktrees.
  - Dependency directories (`node_modules`, `.venv`) are symlinked into snapshots, so a test suite that
    writes into them writes into your real directories. Use `--no-link` to prevent this.
- **Writes escaping a snapshot.** Paths from git are rejected if they are absolute or contain `..`. Overlay
  copies refuse to write through a symlinked directory that resolves outside the snapshot.
- **Runaway processes.** Every run is its own process group. It is killed on timeout, SIGINT or SIGTERM,
  including grandchildren, and temp directories are removed.
- **Hostile inputs.** JUnit reports containing a DTD/entities or larger than 64 MiB are refused. Hook stdin,
  transcripts and agent messages are size-capped and treated purely as data.
- **Loops.** Hook mode sends the agent back at most `max_rounds` times per user turn (default 3).
- **Network.** None by default. `--online` contacts only registry.npmjs.org, pypi.org and crates.io, and
  only for package names newly added to your manifests. There is no telemetry.

### What it does not do

- It does not sandbox your tests. Tests that delete files outside the repo, call production services or
  read secrets will do so in every run. Use a container or VM for untrusted code.
- It does not judge intent. Findings are evidence for a reviewer, not proof of misconduct.

## Reporting a vulnerability

Please use GitHub private vulnerability reporting ("Security" tab → "Report a vulnerability"), not a public
issue. You will get a first response within a week.
