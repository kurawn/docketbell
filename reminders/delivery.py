"""Applies provider delivery events. Duplicates are no-ops; status only moves forward."""

import logging
import uuid
from datetime import datetime

from django.db import transaction
from django.utils import timezone

from reminders.models import Reminder, WebhookEvent
from reminders.providers.base import DeliveryEvent

logger = logging.getLogger(__name__)
Status = Reminder.Status
# Pending is included: after a timeout the provider may have the message while we wait to retry.
UPDATABLE = (Status.PENDING, Status.SENDING, Status.ACCEPTED)


@transaction.atomic
def apply_delivery_event(event: DeliveryEvent, payload: dict, now: datetime | None = None) -> str:
    now = now or timezone.now()
    reminder = _find(event.idempotency_key)
    _, created = WebhookEvent.objects.get_or_create(
        event_id=event.event_id, defaults={"type": event.type, "payload": payload, "reminder": reminder}
    )
    if not created:
        return "duplicate"
    if reminder is None:
        logger.warning("Delivery event %s for unknown key %s", event.event_id, event.idempotency_key)
        return "unknown"
    if reminder.status not in UPDATABLE:
        logger.info("Ignoring %s event for reminder %s in %s", event.type, reminder.pk, reminder.status)
        return "ignored"
    fields = {
        "provider_message_id": reminder.provider_message_id or event.provider_message_id,
        "locked_until": None,
        "updated_at": now,
    }
    if event.type == DeliveryEvent.DELIVERED:
        fields.update(status=Status.DELIVERED, delivered_at=now)
    else:
        fields.update(status=Status.FAILED, last_error=event.reason or "provider reported delivery failure")
    Reminder.objects.filter(pk=reminder.pk).update(**fields)
    return "applied"


def _find(key: str) -> Reminder | None:
    try:
        key = uuid.UUID(key)
    except ValueError:
        return None
    return Reminder.objects.select_for_update().filter(idempotency_key=key).first()
