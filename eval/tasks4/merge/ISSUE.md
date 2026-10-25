`merge` loses nested settings: `merge({"db": {"host": "x", "port": 1}}, {"db": {"port": 2}})` returns
`{"db": {"port": 2}}` but should return `{"db": {"host": "x", "port": 2}}`. Nested dicts must be merged recursively
(at any depth); a non-dict value in `override` still replaces whatever is in `base`. Neither input may be modified.
