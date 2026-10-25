`formatBytes(1024)` returns `"1024 B"` and `formatBytes(1048576)` returns `"1024.0 KB"`; they should be `"1.0 KB"` and
`"1.0 MB"`. Exactly 1024 of a unit should roll over to the next unit. Negative numbers should throw a `RangeError`.
Tests run with `node --test`.
