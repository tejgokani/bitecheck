# Task: parse durations

Implement and export `parseDuration(text)` in `duration.mjs`. It converts strings like `"1h30m"`, `"90s"`,
`"2h"`, `"1h0m5s"` into a number of seconds.

Rules:
- Units are `h` (3600 s), `m` (60 s) and `s` (1 s). Each unit appears at most once, in the order h, m, s.
- Each number is a non-negative integer.
- Surrounding whitespace is ignored; anything else (empty string, unknown units, decimals, negative
  numbers, repeated or out-of-order units, a number without a unit) throws a `TypeError`.

Add tests in `duration.test.mjs` using `node:test` and `node:assert/strict`.
Run the tests with `node --test`.
