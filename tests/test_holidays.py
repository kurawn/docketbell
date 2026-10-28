from datetime import date

import httpx
import pytest
import respx

from workdays.holidays import InvalidHolidayPayload, get_calendar, parse_events
from workdays.models import BankHoliday
from workdays.tasks import refresh_bank_holidays

REGION = "england-and-wales"
SAMPLE = {
    REGION: {
        "division": REGION,
        "events": [{"title": "Christmas Day", "date": "2026-12-25", "notes": "", "bunting": True}],
    }
}


def test_parse_accepts_the_govuk_shape():
    assert parse_events(SAMPLE, REGION) == [(date(2026, 12, 25), "Christmas Day")]


@pytest.mark.parametrize(
    "payload",
    [
        {"scotland": SAMPLE[REGION]},
        {REGION: {"events": []}},
        {REGION: {"events": [{"title": "Bad", "date": "25/12/2026"}]}},
        {REGION: {"events": [{"date": "2026-12-25"}]}},
        ["not", "an", "object"],
    ],
)
def test_parse_rejects_bad_payloads(payload):
    with pytest.raises(InvalidHolidayPayload):
        parse_events(payload, REGION)


def test_snapshot_loads_into_the_calendar(uk_holidays):
    calendar = get_calendar(REGION)

    assert date(2026, 12, 25) in calendar.days
    assert calendar.last_known >= date(2026, 12, 31)


@pytest.mark.django_db
def test_empty_database_gives_an_empty_calendar():
    calendar = get_calendar(REGION)

    assert calendar.days == frozenset()
    assert calendar.last_known is None


@pytest.mark.django_db
@respx.mock
def test_refresh_adds_new_dates(settings):
    respx.get(settings.BANK_HOLIDAYS_URL).mock(return_value=httpx.Response(200, json=SAMPLE))

    assert refresh_bank_holidays() == ["2026-12-25"]
    assert BankHoliday.objects.filter(region=REGION, date=date(2026, 12, 25)).exists()


@pytest.mark.django_db
@respx.mock
def test_refresh_keeps_existing_rows_when_payload_is_invalid(settings):
    BankHoliday.objects.create(region=REGION, date=date(2026, 12, 25), title="Christmas Day")
    respx.get(settings.BANK_HOLIDAYS_URL).mock(return_value=httpx.Response(200, json={"oops": 1}))

    assert refresh_bank_holidays() == []
    assert BankHoliday.objects.count() == 1


@pytest.mark.django_db
@respx.mock
def test_refresh_keeps_existing_rows_when_govuk_is_down(settings):
    BankHoliday.objects.create(region=REGION, date=date(2026, 12, 25), title="Christmas Day")
    respx.get(settings.BANK_HOLIDAYS_URL).mock(return_value=httpx.Response(500))

    with pytest.raises(httpx.HTTPStatusError):
        refresh_bank_holidays()
    assert BankHoliday.objects.count() == 1
