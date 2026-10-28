"""Loads, validates and caches UK bank holidays."""

import time
from dataclasses import dataclass
from datetime import date

from django.conf import settings

from workdays.models import BankHoliday

CACHE_SECONDS = 3600
_cache: dict[str, tuple[float, "HolidayCalendar"]] = {}


@dataclass(frozen=True)
class HolidayCalendar:
    days: frozenset[date]
    last_known: date | None  # 31 Dec of the last year the data covers


class InvalidHolidayPayload(ValueError):
    pass


def get_calendar(region: str | None = None) -> HolidayCalendar:
    region = region or settings.BANK_HOLIDAY_REGION
    cached = _cache.get(region)
    if cached and cached[0] > time.monotonic():
        return cached[1]
    days = frozenset(BankHoliday.objects.filter(region=region).values_list("date", flat=True))
    calendar = HolidayCalendar(days=days, last_known=date(max(days).year, 12, 31) if days else None)
    _cache[region] = (time.monotonic() + CACHE_SECONDS, calendar)
    return calendar


def clear_cache() -> None:
    _cache.clear()


def parse_events(payload: object, region: str) -> list[tuple[date, str]]:
    if not isinstance(payload, dict) or not isinstance(payload.get(region), dict):
        raise InvalidHolidayPayload(f"region {region!r} missing")
    events = payload[region].get("events")
    if not isinstance(events, list) or not events:
        raise InvalidHolidayPayload("events missing or empty")
    parsed = []
    for event in events:
        try:
            parsed.append((date.fromisoformat(event["date"]), str(event["title"])))
        except (KeyError, TypeError, ValueError) as exc:
            raise InvalidHolidayPayload(f"bad event {event!r}") from exc
    return parsed


def upsert_holidays(region: str, events: list[tuple[date, str]]) -> list[date]:
    """Inserts new dates and updates titles; never deletes. Returns the newly added dates."""
    existing = set(BankHoliday.objects.filter(region=region).values_list("date", flat=True))
    BankHoliday.objects.bulk_create(
        [BankHoliday(region=region, date=day, title=title) for day, title in events],
        update_conflicts=True,
        unique_fields=["region", "date"],
        update_fields=["title", "updated_at"],
    )
    clear_cache()
    return sorted({day for day, _ in events} - existing)
