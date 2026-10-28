"""Claims due reminders for sending. Safe to run in parallel thanks to SKIP LOCKED."""

from datetime import datetime, timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from reminders.models import Reminder

Status = Reminder.Status


def dispatch(now: datetime | None = None) -> list:
    now = now or timezone.now()
    limit = settings.DISPATCH_BATCH_SIZE
    with transaction.atomic():
        due = list(
            Reminder.objects.filter(status=Status.PENDING, send_at__lte=now)
            .order_by("send_at")
            .select_for_update(skip_locked=True)
            .values_list("id", flat=True)[:limit]
        )
        # Rows left in "sending" by a worker that died mid-send.
        expired = list(
            Reminder.objects.filter(status=Status.SENDING, locked_until__lt=now)
            .order_by("locked_until")
            .select_for_update(skip_locked=True)
            .values_list("id", flat=True)[:limit]
        )
        claimed = due + expired
        if claimed:
            Reminder.objects.filter(id__in=claimed).update(
                status=Status.SENDING,
                locked_until=now + timedelta(seconds=settings.SEND_LEASE_SECONDS),
                updated_at=now,
            )
            transaction.on_commit(lambda: _enqueue(claimed))
    return claimed


def _enqueue(ids) -> None:
    from reminders.tasks import send_reminder_task

    for reminder_id in ids:
        send_reminder_task.delay(str(reminder_id))
