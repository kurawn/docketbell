import io
import itertools
from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from rest_framework.test import APIClient

from config.celery import app as celery_app
from matters.models import Matter, MatterMember
from matters.services import create_deadline
from reminders.models import Reminder
from workdays.holidays import clear_cache

# Tests never reach Redis: queued tasks go to an in-memory broker and are dropped.
# Namespaced keys, because Celery reads CELERY_* from Django settings before plain keys.
celery_app.conf.update(CELERY_BROKER_URL="memory://", CELERY_TASK_ALWAYS_EAGER=False)

NOW = datetime(2026, 5, 20, 10, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _no_sandbox_faults(settings):
    settings.SANDBOX_FAIL_RATE = 0.0
    settings.SANDBOX_RATE_LIMIT_RATE = 0.0
    settings.SANDBOX_SLOW_RATE = 0.0
    settings.SANDBOX_SLOW_SECONDS = 0
    settings.SANDBOX_DELIVERY_FAIL_RATE = 0.0


@pytest.fixture(autouse=True)
def _fresh_holiday_cache():
    clear_cache()
    yield
    clear_cache()


@pytest.fixture
def uk_holidays(db):
    call_command("load_bank_holidays", stdout=io.StringIO())


@pytest.fixture
def make_user(db):
    def _make(username: str, email: str | None = None):
        email = f"{username}@example.com" if email is None else email
        return get_user_model().objects.create_user(username=username, email=email)

    return _make


@pytest.fixture
def team(make_user):
    return SimpleNamespace(
        attorney=make_user("alice"),
        assistant=make_user("bob"),
        supervisor=make_user("carol"),
        outsider=make_user("dave"),
    )


@pytest.fixture
def matter(team):
    matter = Matter.objects.create(reference="EP-2026-0142", title="Self-cleaning coating", kind="patent")
    for user, role in (
        (team.attorney, MatterMember.Role.RESPONSIBLE),
        (team.assistant, MatterMember.Role.ASSISTANT),
        (team.supervisor, MatterMember.Role.SUPERVISOR),
    ):
        MatterMember.objects.create(matter=matter, user=user, role=role)
    return matter


@pytest.fixture
def api():
    def _for(user):
        client = APIClient()
        client.force_authenticate(user)
        return client

    return _for


@pytest.fixture
def now():
    return NOW


@pytest.fixture
def deadline(matter, uk_holidays):
    return create_deadline(
        matter=matter,
        kind="office_action_response",
        title="Respond to examination report",
        nominal_date=date(2026, 6, 13),
        now=NOW,
    )


@pytest.fixture
def make_reminder(deadline, team):
    offsets = itertools.count(100)  # stays clear of the planner's offsets

    def _make(**overrides):
        fields = {
            "deadline": deadline,
            "recipient": team.attorney,
            "type": Reminder.Type.REMINDER,
            "offset_days": next(offsets),
            "for_due_date": deadline.due_date,
            "send_at": NOW,
            "status": Reminder.Status.PENDING,
        }
        fields.update(overrides)
        return Reminder.objects.create(**fields)

    return _make
