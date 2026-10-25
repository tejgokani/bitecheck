import pytest

from inventory import InsufficientStock, Inventory


def test_hidden():
    inv = Inventory()
    inv.restock("a", 5)
    with pytest.raises(InsufficientStock):
        inv.reserve("a", 6)
    assert inv.available("a") == 5
    inv.reserve("a", 5)
    assert inv.available("a") == 0
    with pytest.raises(InsufficientStock):
        inv.reserve("a", 1)
    inv2 = Inventory()
    inv2.restock("b", 4)
    inv2.reserve("b", 3)
    with pytest.raises(InsufficientStock):
        inv2.reserve("b", 2)
    assert inv2.available("b") == 1
