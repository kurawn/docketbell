"""UK working-day arithmetic. Pure functions; callers pass the holiday set."""

from datetime import date, timedelta

Holidays = frozenset[date]


def is_working_day(day: date, holidays: Holidays) -> bool:
    return day.weekday() < 5 and day not in holidays


def roll_forward(day: date, holidays: Holidays) -> date:
    while not is_working_day(day, holidays):
        day += timedelta(days=1)
    return day


def working_days_before(day: date, n: int, holidays: Holidays) -> date:
    remaining = n
    while remaining > 0:
        day -= timedelta(days=1)
        if is_working_day(day, holidays):
            remaining -= 1
    return day
