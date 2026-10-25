`Truncate` counts bytes, not characters: `Truncate("héllo wörld", 5)` can return invalid UTF-8, and
`Truncate("héllo", 5)` truncates a string that already fits in 5 characters. It must count Unicode code points
(runes): strings of at most n runes are returned unchanged, longer strings become their first n-1 runes plus "…".
For n < 1 return "". Tests run with `go test ./...`.
