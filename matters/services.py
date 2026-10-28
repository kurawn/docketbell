"""Deadline and membership operations; views stay thin and call these."""

from datetime import date, datetime

from django.db import transaction
from django.utils import timezone

from matters.models import Deadline, MatterMember
from reminders.models import Reminder
from reminders.planner import cancel_pending, plan_reminders, replan
from workdays.calendar import roll_forward
from workdays.holidays import get_calendar


class DeadlineClosed(Exception):
    """A completed or cancelled deadline cannot change."""


def compute_due_date(nominal: date) -> tuple[date, bool]:
    calendar = get_calendar()
    due = roll_forward(nominal, calendar.days)
    complete = calendar.last_known is not None and due <= calendar.last_known
    return due, complete


@transaction.atomic
def create_deadline(
    *, matter, kind, title, nominal_date, reminder_offsets=None, now: datetime | None = None
) -> Deadline:
    deadline = Deadline(matter=matter, kind=kind, title=title, nominal_date=nominal_date)
    if reminder_offsets is not None:
        deadline.reminder_offsets = reminder_offsets
    deadline.due_date, deadline.holiday_data_complete = compute_due_date(nominal_date)
    deadline.save()
    plan_reminders(deadline, now or timezone.now())
    return deadline


@transaction.atomic
def update_deadline(deadline_id, changes: dict, now: datetime | None = None) -> Deadline:
    deadline = Deadline.objects.select_for_update().get(pk=deadline_id)
    if deadline.status != Deadline.Status.OPEN:
        raise DeadlineClosed
    for field, value in changes.items():
        setattr(deadline, field, value)
    if "nominal_date" in changes:
        deadline.due_date, deadline.holiday_data_complete = compute_due_date(deadline.nominal_date)
    deadline.save()
    if deadline.status != Deadline.Status.OPEN:
        cancel_pending(deadline)
    elif changes.keys() & {"nominal_date", "reminder_offsets"}:
        replan(deadline, now or timezone.now())
    return deadline


@transaction.atomic
def add_member(*, matter, user, role, now: datetime | None = None) -> MatterMember:
    member = MatterMember.objects.create(matter=matter, user=user, role=role)
    for deadline in matter.deadlines.filter(status=Deadline.Status.OPEN).select_for_update():
        plan_reminders(deadline, now or timezone.now())
    return member


@transaction.atomic
def acknowledge_deadline(deadline_id, user, now: datetime | None = None) -> Deadline:
    deadline = Deadline.objects.select_for_update().get(pk=deadline_id)
    if deadline.status != Deadline.Status.OPEN:
        raise DeadlineClosed
    if deadline.acknowledged_at is None:
        deadline.acknowledged_by = user
        deadline.acknowledged_at = now or timezone.now()
        deadline.save(update_fields=["acknowledged_by", "acknowledged_at", "updated_at"])
        cancel_pending(deadline, types=[Reminder.Type.ESCALATION])
    return deadline


def recompute_after_holiday_change(added: list[date], now: datetime | None = None) -> int:
    """Re-rolls open deadlines a newly announced holiday could affect, one row lock at a time."""
    if not added:
        return 0
    now = now or timezone.now()
    count = 0
    candidates = Deadline.objects.filter(status=Deadline.Status.OPEN, due_date__gte=min(added))
    for deadline_id in candidates.values_list("id", flat=True):
        with transaction.atomic():
            deadline = Deadline.objects.select_for_update().get(pk=deadline_id)
            if deadline.status != Deadline.Status.OPEN:
                continue
            deadline.due_date, deadline.holiday_data_complete = compute_due_date(deadline.nominal_date)
            deadline.save(update_fields=["due_date", "holiday_data_complete", "updated_at"])
            replan(deadline, now)
        count += 1
    return count
