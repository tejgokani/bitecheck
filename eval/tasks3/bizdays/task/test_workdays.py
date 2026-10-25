from datetime import date

from workdays import business_days_between


def test_same_day_is_zero():
    assert business_days_between(date(2026, 3, 2), date(2026, 3, 2)) == 0


def test_monday_to_wednesday():
    assert business_days_between(date(2026, 3, 2), date(2026, 3, 4)) == 2
