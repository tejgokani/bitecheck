import pytest
from shipping import shipping_cost


@pytest.mark.parametrize("w,z,e,exp", [
    (1.0, "domestic", False, 5.0), (1.2, "domestic", False, 7.0), (3.0, "eu", False, 16.0), (3.1, "eu", False, 18.0),
    (2.0, "intl", True, 54.0), (0.5, "domestic", False, 0.0), (0.5, "domestic", True, 10.0), (0.5, "eu", False, 12.0),
    (0.6, "domestic", False, 5.0),
])
def test_cost(w, z, e, exp):
    assert shipping_cost(w, z, e) == exp


@pytest.mark.parametrize("w,z", [(1, "mars"), (0, "eu"), (-1, "domestic")])
def test_errors(w, z):
    with pytest.raises(ValueError):
        shipping_cost(w, z)
