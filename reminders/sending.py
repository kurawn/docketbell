"""Sends one claimed reminder. Every write is conditional on the row still being ours."""

import logging
import random
from dataclasses import asdict
from datetime import datetime, timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from matters.models import Deadline
from reminders.messages import compose
from reminders.models import Reminder
from reminders.providers import get_provider
from reminders.providers.base import (
    MessagingProvider,
    OutboundMessage,
    PermanentProviderError,
    TransientProviderError,
)

logger = logging.getLogger(__name__)
BACKOFF_STEPS = (30, 120, 480, 1800)
Status = Reminder.Status


def backoff_seconds(attempts: int) -> float:
    return BACKOFF_STEPS[min(attempts, len(BACKOFF_STEPS)) - 1] * random.uniform(0.8, 1.2)


def send_reminder(reminder_id, provider: MessagingProvider | None = None, now: datetime | None = None) -> str:
    now = now or timezone.now()
    reminder = Reminder.objects.select_related("deadline__matter", "recipient").filter(pk=reminder_id).first()
    if reminder is None or reminder.status != Status.SENDING:
        return "skipped"
    claimed = Reminder.objects.filter(pk=reminder.pk, status=Status.SENDING)

    def finish(status: str, **fields) -> str:
        claimed.update(status=status, locked_until=None, updated_at=now, **fields)
        return status

    deadline = reminder.deadline
    if (
        deadline.status != Deadline.Status.OPEN
        or reminder.for_due_date != deadline.due_date  # the deadline moved; a replacement is planned
        or (reminder.type == Reminder.Type.ESCALATION and deadline.acknowledged_at)
    ):
        return finish(Status.CANCELLED)
    if reminder.attempts >= settings.MAX_SEND_ATTEMPTS:
        return finish(Status.FAILED, last_error=f"gave up after {reminder.attempts} attempts")
    if not reminder.recipient.email:
        return finish(Status.FAILED, last_error="recipient has no email address")

    payload = reminder.payload or asdict(compose(reminder))
    attempts = reminder.attempts + 1
    if not claimed.update(payload=payload, attempts=attempts):
        return "skipped"

    try:
        result = (provider or get_provider()).send(OutboundMessage(**payload), str(reminder.idempotency_key))
    except PermanentProviderError as exc:
        return finish(Status.FAILED, last_error=str(exc))
    except Exception as exc:
        if not isinstance(exc, TransientProviderError):
            logger.exception("Unexpected error sending reminder %s", reminder.pk)
        if attempts >= settings.MAX_SEND_ATTEMPTS:
            return finish(Status.FAILED, last_error=str(exc))
        delay = max(backoff_seconds(attempts), getattr(exc, "retry_after", None) or 0)
        return finish(Status.PENDING, send_at=now + timedelta(seconds=delay), last_error=str(exc))

    with transaction.atomic():
        # The delivery webhook may already have moved the row on; the message id is still worth keeping.
        Reminder.objects.filter(pk=reminder.pk).update(
            provider_message_id=result.provider_message_id, sent_at=now, last_error=""
        )
        finish(Status.ACCEPTED)
    return Status.ACCEPTED
