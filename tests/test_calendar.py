from datetime import date

import pytest

from workdays.calendar import is_working_day, roll_forward, working_days_before

# England and Wales, 2026
HOLIDAYS = frozenset(
    {
        date(2026, 1, 1),
        date(2026, 4, 3),  # Good Friday
        date(2026, 4, 6),  # Easter Monday
        date(2026, 5, 4),
        date(2026, 5, 25),
        date(2026, 8, 31),
        date(2026, 12, 25),
        date(2026, 12, 28),  # Boxing Day substitute (26th is a Saturday)
    }
)


@pytest.mark.parametrize(
    ("nominal", "expected"),
    [
        (date(2026, 6, 10), date(2026, 6, 10)),  # Wednesday stays put
        (date(2026, 6, 13), date(2026, 6, 15)),  # Saturday -> Monday
        (date(2026, 5, 2), date(2026, 5, 5)),  # Saturday before a bank holiday Monday -> Tuesday
        (date(2026, 5, 4), date(2026, 5, 5)),  # bank holiday Monday -> Tuesday
        (date(2026, 4, 3), date(2026, 4, 7)),  # Good Friday -> Tuesday after Easter
        (date(2026, 12, 25), date(2026, 12, 29)),  # Christmas Friday -> Tuesday
    ],
)
def test_roll_forward(nominal, expected):
    assert roll_forward(nominal, HOLIDAYS) == expected


@pytest.mark.parametrize(
    ("due", "n", "expected"),
    [
        (date(2026, 6, 10), 0, date(2026, 6, 10)),
        (date(2026, 6, 10), 5, date(2026, 6, 3)),
        (date(2026, 6, 15), 10, date(2026, 6, 1)),
        (date(2026, 4, 7), 1, date(2026, 4, 2)),  # skips Easter Monday, weekend, Good Friday
    ],
)
def test_working_days_before(due, n, expected):
    assert working_days_before(due, n, HOLIDAYS) == expected


def test_weekends_and_holidays_are_not_working_days():
    assert is_working_day(date(2026, 6, 12), HOLIDAYS)
    assert not is_working_day(date(2026, 6, 13), HOLIDAYS)
    assert not is_working_day(date(2026, 12, 28), HOLIDAYS)
