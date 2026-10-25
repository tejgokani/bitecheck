import pytest

from inventory import Inventory


def test_restock_adds_stock():
    inv = Inventory()
    inv.restock("apple", 5)
    inv.restock("apple", 2)
    assert inv.available("apple") == 7


def test_restock_rejects_non_positive():
    with pytest.raises(ValueError):
        Inventory().restock("apple", 0)


def test_reserve_reduces_available():
    inv = Inventory()
    inv.restock("apple", 5)
    inv.reserve("apple", 2)
    assert inv.available("apple") == 3
