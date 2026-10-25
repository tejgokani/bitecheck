`parseQuery` mishandles real query strings: `parseQuery("q=hello+world&flag&x=a%3Db")` returns `q: "hello+world"`,
`flag: "undefined"`, and `x: "a=b"` only by luck. Expected `{ q: "hello world", flag: "", x: "a=b" }`: `+` means a space,
a key without `=` gets `""`, only the first `=` splits key from value, and empty segments (`a=1&&b=2`, or an empty
string) are ignored. Tests run with `node --test`.
