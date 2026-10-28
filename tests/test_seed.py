import io

import pytest
from django.core.management import call_command

from matters.models import Matter
from reminders.models import Reminder

pytestmark = pytest.mark.django_db


def test_seed_demo_is_idempotent_and_plans_reminders(uk_holidays, settings):
    settings.DEBUG = True

    call_command("seed_demo", stdout=io.StringIO())
    call_command("seed_demo", stdout=io.StringIO())

    assert Matter.objects.filter(reference="EP-2026-0142").count() == 1
    assert Reminder.objects.exists()


def test_seed_demo_refuses_to_run_without_debug(settings):
    settings.DEBUG = False

    with pytest.raises(Exception, match="DEBUG"):
        call_command("seed_demo", stdout=io.StringIO())
