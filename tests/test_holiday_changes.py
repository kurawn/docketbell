import json
from datetime import date

import httpx
import pytest
import respx

from matters.services import recompute_after_holiday_change
from workdays.holidays import upsert_holidays
from workdays.management.commands.load_bank_holidays import SNAPSHOT
from workdays.tasks import refresh_bank_holidays

pytestmark = pytest.mark.django_db
SURPRISE = date(2026, 6, 15)  # the Monday the test deadline rolls to


def test_new_holiday_moves_an_open_deadline_and_replans(deadline, settings, now):
    upsert_holidays(settings.BANK_HOLIDAY_REGION, [(SURPRISE, "Surprise holiday")])

    assert recompute_after_holiday_change([SURPRISE], now=now) == 1

    deadline.refresh_from_db()
    assert deadline.due_date == date(2026, 6, 16)
    live = deadline.reminders.exclude(status="cancelled")
    assert set(live.values_list("for_due_date", flat=True)) == {date(2026, 6, 16)}


def test_closed_deadlines_are_left_alone(deadline, settings, now):
    deadline.status = "completed"
    deadline.save()
    upsert_holidays(settings.BANK_HOLIDAY_REGION, [(SURPRISE, "Surprise holiday")])

    assert recompute_after_holiday_change([SURPRISE], now=now) == 0


@respx.mock
def test_refresh_that_adds_a_holiday_moves_deadlines(deadline, settings):
    payload = json.loads(SNAPSHOT.read_text())
    payload[settings.BANK_HOLIDAY_REGION]["events"].append(
        {"title": "Surprise holiday", "date": SURPRISE.isoformat(), "notes": "", "bunting": False}
    )
    respx.get(settings.BANK_HOLIDAYS_URL).mock(return_value=httpx.Response(200, json=payload))

    assert refresh_bank_holidays() == [SURPRISE.isoformat()]

    deadline.refresh_from_db()
    assert deadline.due_date == date(2026, 6, 16)
