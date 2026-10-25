def merge(base: dict, override: dict) -> dict:
    """Return a new dict: `override` applied on top of `base`. Neither input is modified."""
    out = dict(base)
    out.update(override)
    return out
