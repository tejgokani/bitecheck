import pytest

from pages import paginate


def test_hidden():
    assert paginate(range(10), 1, 5) == [0, 1, 2, 3, 4]
    assert paginate(range(10), 2, 5) == [5, 6, 7, 8, 9]
    assert paginate(range(10), 3, 5) == []
    assert paginate(range(7), 2, 5) == [5, 6]
    for bad in (0, -1):
        with pytest.raises(ValueError):
            paginate(range(3), bad)
