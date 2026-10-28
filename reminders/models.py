import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q

from core.models import BaseModel


class Reminder(BaseModel):
    class Type(models.TextChoices):
        REMINDER = "reminder"
        ESCALATION = "escalation"

    class Status(models.TextChoices):
        PENDING = "pending"
        SENDING = "sending"
        ACCEPTED = "accepted"
        DELIVERED = "delivered"
        FAILED = "failed"
        CANCELLED = "cancelled"

    deadline = models.ForeignKey("matters.Deadline", on_delete=models.CASCADE, related_name="reminders")
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    type = models.CharField(max_length=16, choices=Type.choices, default=Type.REMINDER)
    offset_days = models.PositiveSmallIntegerField()
    for_due_date = models.DateField()
    send_at = models.DateTimeField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    locked_until = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    last_error = models.TextField(blank=True, default="")
    idempotency_key = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    payload = models.JSONField(null=True, blank=True)  # message frozen on first attempt
    provider_message_id = models.CharField(max_length=100, blank=True, default="")
    sent_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["deadline", "recipient", "offset_days", "type", "for_due_date"],
                condition=~Q(status="cancelled"),
                name="uniq_live_reminder",
            )
        ]
        indexes = [
            models.Index(fields=["send_at"], condition=Q(status="pending"), name="reminder_due_idx"),
            models.Index(fields=["locked_until"], condition=Q(status="sending"), name="reminder_lease_idx"),
        ]


class WebhookEvent(BaseModel):
    event_id = models.CharField(max_length=200, unique=True)
    type = models.CharField(max_length=32)
    payload = models.JSONField()
    reminder = models.ForeignKey(Reminder, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
