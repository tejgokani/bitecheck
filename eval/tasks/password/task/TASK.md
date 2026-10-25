# Task: password policy

Implement `violations(password: str, banned: list[str] = ()) -> list[str]` in `policy.py`.

It returns the list of rule codes the password breaks, in this order, each at most once:

- `"length"`: fewer than 12 characters
- `"digit"`: no digit
- `"upper"`: no uppercase letter
- `"lower"`: no lowercase letter
- `"space"`: contains any whitespace character
- `"banned"`: equals one of `banned`, compared case-insensitively

A valid password returns `[]`.

Add thorough tests in `test_policy.py` (pytest).
