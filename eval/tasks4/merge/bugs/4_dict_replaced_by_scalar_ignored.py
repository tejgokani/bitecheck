def merge(base: dict, override: dict) -> dict:
    """Return a new dict: `override` applied on top of `base`. Neither input is modified."""
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = merge(out[key], value)
        elif not isinstance(out.get(key), dict):
            out[key] = value
    return out
