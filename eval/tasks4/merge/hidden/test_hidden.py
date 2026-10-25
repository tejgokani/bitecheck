from config import merge


def test_hidden():
    assert merge({"db": {"host": "x", "port": 1}}, {"db": {"port": 2}}) == {"db": {"host": "x", "port": 2}}
    assert merge({"a": {"b": {"c": 1, "d": 2}}}, {"a": {"b": {"d": 3}}}) == {"a": {"b": {"c": 1, "d": 3}}}
    base = {"db": {"host": "x"}}
    merge(base, {"db": {"host": "y"}})
    assert base == {"db": {"host": "x"}}
    assert merge({"db": {"host": "x"}}, {"db": None}) == {"db": None}
