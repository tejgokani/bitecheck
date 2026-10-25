def merge(base: dict, override: dict) -> dict:
    """Return a new dict: `override` applied on top of `base`. Neither input is modified."""
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = {**out[key], **value}
        else:
            out[key] = value
    return out
