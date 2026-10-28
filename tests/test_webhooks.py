import json
import time

import pytest
from rest_framework.test import APIClient

from reminders.models import WebhookEvent
from sandbox.signing import sign

pytestmark = pytest.mark.django_db
URL = "/api/v1/webhooks/provider/"


def post_event(reminder, settings, event_id="evt-1", type_="message.delivered", secret=None, timestamp=None):
    body = json.dumps(
        {
            "event_id": event_id,
            "type": type_,
            "message_id": "m-1",
            "idempotency_key": str(reminder.idempotency_key),
            "occurred_at": "2026-06-01T08:00:00+00:00",
            "reason": "mailbox full" if type_ == "message.failed" else "",
        }
    ).encode()
    signature = sign(secret or settings.WEBHOOK_SECRET, timestamp or int(time.time()), body)
    return APIClient().post(
        URL, data=body, content_type="application/json", HTTP_X_SANDBOX_SIGNATURE=signature
    )


def status_of(reminder):
    reminder.refresh_from_db()
    return reminder.status


def test_delivered_event_moves_accepted_to_delivered(make_reminder, settings):
    reminder = make_reminder(status="accepted")

    response = post_event(reminder, settings)

    assert response.status_code == 200
    assert status_of(reminder) == "delivered"
    assert reminder.delivered_at is not None


def test_failed_event_records_the_reason(make_reminder, settings):
    reminder = make_reminder(status="accepted")

    post_event(reminder, settings, type_="message.failed")

    assert status_of(reminder) == "failed"
    assert reminder.last_error == "mailbox full"


def test_bad_signature_is_rejected(make_reminder, settings):
    reminder = make_reminder(status="accepted")

    response = post_event(reminder, settings, secret="wrong")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_signature"
    assert status_of(reminder) == "accepted"


def test_stale_timestamp_is_rejected(make_reminder, settings):
    reminder = make_reminder(status="accepted")

    assert post_event(reminder, settings, timestamp=int(time.time()) - 600).status_code == 401


def test_non_ascii_signature_is_rejected_not_a_server_error():
    signature = f"t={int(time.time())},v1=é"

    response = APIClient().post(
        URL, data=b"{}", content_type="application/json", HTTP_X_SANDBOX_SIGNATURE=signature
    )

    assert response.status_code == 401


def test_duplicate_event_is_ignored(make_reminder, settings):
    reminder = make_reminder(status="accepted")
    post_event(reminder, settings, event_id="evt-1")

    response = post_event(reminder, settings, event_id="evt-1", type_="message.failed")

    assert response.json() == {"status": "duplicate"}
    assert status_of(reminder) == "delivered"
    assert WebhookEvent.objects.count() == 1


def test_late_event_cannot_move_a_reminder_backwards(make_reminder, settings):
    reminder = make_reminder(status="accepted")
    post_event(reminder, settings, event_id="evt-1")

    response = post_event(reminder, settings, event_id="evt-2", type_="message.failed")

    assert response.json() == {"status": "ignored"}
    assert status_of(reminder) == "delivered"


def test_event_before_our_accepted_update_still_applies(make_reminder, settings):
    reminder = make_reminder(status="sending")

    post_event(reminder, settings)

    assert status_of(reminder) == "delivered"


def test_event_during_backoff_after_a_timeout_applies(make_reminder, settings):
    reminder = make_reminder(status="pending", attempts=1, last_error="ReadTimeout")

    post_event(reminder, settings)

    assert status_of(reminder) == "delivered"


def test_unknown_reminder_is_acknowledged_so_the_provider_stops_retrying(make_reminder, settings):
    reminder = make_reminder(status="accepted")
    reminder.idempotency_key = "00000000-0000-0000-0000-000000000000"

    response = post_event(reminder, settings)

    assert response.status_code == 200
    assert response.json() == {"status": "unknown"}
