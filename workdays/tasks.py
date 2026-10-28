import logging

import httpx
from celery import shared_task
from django.conf import settings

from workdays.holidays import InvalidHolidayPayload, parse_events, upsert_holidays

logger = logging.getLogger(__name__)


@shared_task(
    name="workdays.refresh_bank_holidays",
    autoretry_for=(httpx.TransportError, httpx.HTTPStatusError),
    retry_backoff=60,
    max_retries=3,
)
def refresh_bank_holidays() -> list[str]:
    region = settings.BANK_HOLIDAY_REGION
    response = httpx.get(settings.BANK_HOLIDAYS_URL, timeout=5.0)
    response.raise_for_status()
    try:
        events = parse_events(response.json(), region)
    except (InvalidHolidayPayload, ValueError):
        logger.error("Rejected GOV.UK bank holiday payload; keeping existing data", exc_info=True)
        return []
    added = upsert_holidays(region, events)
    if added:
        from matters.services import recompute_after_holiday_change  # matters depends on workdays, not back

        recompute_after_holiday_change(added)
    return [day.isoformat() for day in added]
