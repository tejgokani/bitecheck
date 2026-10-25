`ParsePort` accepts invalid ports: `ParsePort("0")`, `ParsePort("-5")` and `ParsePort("70000")` all succeed.
Valid TCP ports are 1 through 65535 inclusive; anything else must return an error. Tests run with `go test ./...`.
