from config import merge


def test_override_wins():
    assert merge({"a": 1, "b": 2}, {"b": 3}) == {"a": 1, "b": 3}


def test_inputs_untouched():
    base = {"a": 1}
    merge(base, {"a": 2})
    assert base == {"a": 1}
