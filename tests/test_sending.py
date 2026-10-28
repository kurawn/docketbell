from datetime import date, timedelta

import httpx
import pytest

from matters.services import update_deadline
from reminders.models import Reminder
from reminders.providers.base import PermanentProviderError, TransientProviderError
from reminders.providers.sandbox import SandboxProvider
from reminders.sending import send_reminder
from sandbox.models import SandboxMessage
from tests.fakes import DjangoClientTransport, FakeProvider

pytestmark = pytest.mark.django_db


@pytest.fixture
def claimed(make_reminder, now):
    return make_reminder(status="sending", locked_until=now + timedelta(minutes=2))


def reload(reminder):
    reminder.refresh_from_db()
    return reminder


def reclaim(reminder):
    Reminder.objects.filter(pk=reminder.pk).update(status="sending")


def test_success_marks_accepted(claimed, now):
    provider = FakeProvider("msg-1")

    assert send_reminder(claimed.pk, provider=provider, now=now) == "accepted"

    reminder = reload(claimed)
    assert (reminder.status, reminder.provider_message_id, reminder.attempts) == ("accepted", "msg-1", 1)
    assert reminder.sent_at == now and reminder.locked_until is None
    message, key = provider.calls[0]
    assert key == str(claimed.idempotency_key)
    assert message.to == "alice@example.com"


def test_transient_failure_goes_back_to_pending_later(claimed, now):
    send_reminder(claimed.pk, provider=FakeProvider(TransientProviderError("503")), now=now)

    reminder = reload(claimed)
    assert reminder.status == "pending"
    assert now + timedelta(seconds=24) <= reminder.send_at <= now + timedelta(seconds=36)
    assert reminder.last_error == "503"


def test_retry_after_is_respected(claimed, now):
    send_reminder(claimed.pk, provider=FakeProvider(TransientProviderError("429", retry_after=3600)), now=now)

    assert reload(claimed).send_at == now + timedelta(seconds=3600)


def test_permanent_failure_is_final(claimed, now):
    assert (
        send_reminder(claimed.pk, provider=FakeProvider(PermanentProviderError("400")), now=now) == "failed"
    )


def test_last_allowed_attempt_fails_for_good(claimed, now, settings):
    Reminder.objects.filter(pk=claimed.pk).update(attempts=settings.MAX_SEND_ATTEMPTS - 1)

    assert (
        send_reminder(claimed.pk, provider=FakeProvider(TransientProviderError("503")), now=now) == "failed"
    )


def test_reminder_that_keeps_crashing_the_worker_is_failed(claimed, now, settings):
    Reminder.objects.filter(pk=claimed.pk).update(attempts=settings.MAX_SEND_ATTEMPTS)
    provider = FakeProvider()

    assert send_reminder(claimed.pk, provider=provider, now=now) == "failed"
    assert provider.calls == []


def test_unclaimed_reminder_is_skipped(make_reminder, now):
    reminder = make_reminder(status="pending")
    provider = FakeProvider()

    assert send_reminder(reminder.pk, provider=provider, now=now) == "skipped"
    assert provider.calls == []


def test_closed_deadline_cancels_instead_of_sending(claimed, deadline, now):
    deadline.status = "completed"
    deadline.save()

    assert send_reminder(claimed.pk, provider=FakeProvider(), now=now) == "cancelled"


def test_acknowledged_deadline_cancels_its_escalation(make_reminder, deadline, team, now):
    escalation = make_reminder(status="sending", type="escalation", recipient=team.supervisor)
    deadline.acknowledged_at = now
    deadline.save()

    assert send_reminder(escalation.pk, provider=FakeProvider(), now=now) == "cancelled"


def test_reminder_for_a_moved_due_date_is_cancelled(claimed, deadline, now):
    update_deadline(deadline.pk, {"nominal_date": date(2026, 6, 20)}, now=now)
    provider = FakeProvider()

    assert send_reminder(claimed.pk, provider=provider, now=now) == "cancelled"
    assert provider.calls == []


def test_recipient_without_email_fails_without_calling_the_provider(make_reminder, make_user, now):
    reminder = make_reminder(status="sending", recipient=make_user("noemail", email=""))
    provider = FakeProvider()

    assert send_reminder(reminder.pk, provider=provider, now=now) == "failed"
    assert reload(reminder).last_error == "recipient has no email address"
    assert provider.calls == []


def test_payload_is_frozen_across_retries(claimed, deadline, now):
    provider = FakeProvider(TransientProviderError("503"), "msg-1")
    send_reminder(claimed.pk, provider=provider, now=now)
    deadline.title = "Renamed between attempts"
    deadline.save()
    reclaim(claimed)

    send_reminder(claimed.pk, provider=provider, now=now)

    first, second = provider.calls
    assert first == second


@pytest.mark.urls("config.urls_sandbox")
def test_timeout_after_the_provider_stored_the_message_sends_once(claimed, now, settings):
    client = httpx.Client(
        transport=DjangoClientTransport(timeout_first=1),
        base_url="http://provider",
        headers={"Authorization": f"Bearer {settings.SANDBOX_API_KEY}"},
    )
    provider = SandboxProvider(client=client)

    assert send_reminder(claimed.pk, provider=provider, now=now) == "pending"
    assert SandboxMessage.objects.count() == 1

    reclaim(claimed)
    assert send_reminder(claimed.pk, provider=provider, now=now) == "accepted"

    reminder = reload(claimed)
    assert SandboxMessage.objects.count() == 1
    assert reminder.provider_message_id == str(SandboxMessage.objects.get().id)
    assert reminder.attempts == 2
