from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import Q

from core.models import BaseModel


class Matter(BaseModel):
    class Kind(models.TextChoices):
        PATENT = "patent"
        TRADEMARK = "trademark"

    reference = models.CharField(max_length=40, unique=True)
    title = models.CharField(max_length=200)
    kind = models.CharField(max_length=16, choices=Kind.choices)


class MatterMember(BaseModel):
    class Role(models.TextChoices):
        RESPONSIBLE = "responsible"
        ASSISTANT = "assistant"
        SUPERVISOR = "supervisor"

    matter = models.ForeignKey(Matter, on_delete=models.CASCADE, related_name="members")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField(max_length=16, choices=Role.choices)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["matter", "user"], name="uniq_matter_member")]


REMINDER_ROLES = (MatterMember.Role.RESPONSIBLE, MatterMember.Role.ASSISTANT)
EDITOR_ROLES = (MatterMember.Role.RESPONSIBLE, MatterMember.Role.SUPERVISOR)


def default_offsets() -> list[int]:
    return [10, 5, 1]


class Deadline(BaseModel):
    class Kind(models.TextChoices):
        OFFICE_ACTION_RESPONSE = "office_action_response"
        RENEWAL_FEE = "renewal_fee"
        OTHER = "other"

    class Status(models.TextChoices):
        OPEN = "open"
        COMPLETED = "completed"
        CANCELLED = "cancelled"

    matter = models.ForeignKey(Matter, on_delete=models.CASCADE, related_name="deadlines")
    kind = models.CharField(max_length=32, choices=Kind.choices)
    title = models.CharField(max_length=200)
    nominal_date = models.DateField()
    due_date = models.DateField()
    reminder_offsets = ArrayField(models.PositiveSmallIntegerField(), default=default_offsets)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN)
    acknowledged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    holiday_data_complete = models.BooleanField(default=True)

    class Meta:
        indexes = [
            models.Index(fields=["matter", "due_date"], name="deadline_matter_due_idx"),
            models.Index(fields=["due_date"], condition=Q(status="open"), name="deadline_open_due_idx"),
        ]

    @property
    def rolled(self) -> bool:
        return self.due_date != self.nominal_date
