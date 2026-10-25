from datetime import date

from workdays import business_days_between as b


def test_hidden():
    assert b(date(2026, 3, 2), date(2026, 3, 9)) == 5
    assert b(date(2026, 3, 6), date(2026, 3, 9)) == 1
    assert b(date(2026, 3, 7), date(2026, 3, 9)) == 0
    assert b(date(2026, 3, 2), date(2026, 3, 30)) == 20
    assert b(date(2026, 3, 9), date(2026, 3, 2)) == 0
    assert b(date(2026, 3, 8), date(2026, 3, 10)) == 1
