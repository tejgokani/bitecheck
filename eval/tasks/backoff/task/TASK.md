# Task: retry backoff

Implement `Delay(attempt int, base, max time.Duration) time.Duration` in `backoff.go` (package `backoff`).

Rules:
- `attempt` counts from 1. For `attempt < 1` return 0.
- The delay is `base * 2^(attempt-1)`: attempt 1 → base, attempt 2 → 2×base, attempt 3 → 4×base, …
- The result never exceeds `max`; once the doubling would pass `max`, return exactly `max`.
- It must not overflow for large attempts (e.g. attempt 200 returns `max`).
- If `base <= 0` or `max <= 0`, return 0.

Add thorough tests in `backoff_test.go`. Run them with `go test ./...`.
