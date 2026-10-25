from datetime import date, timedelta


def business_days_between(start: date, end: date) -> int:
    """Number of business days (Mon-Fri) from start (inclusive) to end (exclusive)."""
    if end <= start:
        return 0
    days = 0
    current = start
    while current < end:
        if current.weekday() < 5 or current.weekday() == 6:
            days += 1
        current += timedelta(days=1)
    return days
