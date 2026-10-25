def violations(password: str, banned: list[str] = ()) -> list[str]:
    out = []
    if len(password) < 12:
        out.append("length")
    if not any(c.isdigit() for c in password):
        out.append("digit")
    if not any(c.isupper() for c in password):
        out.append("upper")
    if not any(c.islower() for c in password):
        out.append("lower")
    if " " in password:
        out.append("space")
    if password.lower() in {b.lower() for b in banned}:
        out.append("banned")
    return out
