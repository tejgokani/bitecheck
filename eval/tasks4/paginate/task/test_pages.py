from pages import page_count, paginate


def test_page_count():
    assert page_count(range(25), 10) == 3
    assert page_count([], 10) == 0


def test_paginate_returns_a_list():
    assert isinstance(paginate(range(3), 1), list)
