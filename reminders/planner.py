"""Turns a deadline into reminder rows. Additive and safe to call repeatedly."""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils import timezone

from matters.models import REMINDER_ROLES, MatterMember
from reminders.models import Reminder
from workdays.calendar import working_days_before
from workdays.holidays import get_calendar


def local_time(day: date, hour: int) -> datetime:
    return datetime.combine(day, time(hour), tzinfo=ZoneInfo(settings.TIME_ZONE))


def plan_reminders(deadline, now: datetime) -> list[Reminder]:
    holidays = get_calendar().days
    planned = set(
        deadline.reminders.exclude(status=Reminder.Status.CANCELLED)
        .filter(for_due_date=deadline.due_date)
        .values_list("recipient_id", "offset_days", "type")
    )
    schedule = [
        (
            offset,
            local_time(working_days_before(deadline.due_date, offset, holidays), settings.REMINDER_SEND_HOUR),
        )
        for offset in sorted(deadline.reminder_offsets, reverse=True)
    ]
    rows = []
    for member in MatterMember.objects.filter(matter_id=deadline.matter_id):
        if member.role in REMINDER_ROLES:
            rows += _reminders_for(deadline, member.user_id, schedule, planned, now)
        elif member.role == MatterMember.Role.SUPERVISOR and deadline.acknowledged_at is None:
            rows += _escalation_for(deadline, member.user_id, schedule, planned, now)
    return Reminder.objects.bulk_create(rows)


def cancel_pending(deadline, types=None) -> int:
    rows = deadline.reminders.filter(status=Reminder.Status.PENDING)
    if types is not None:
        rows = rows.filter(type__in=types)
    return rows.update(status=Reminder.Status.CANCELLED, updated_at=timezone.now())


def replan(deadline, now: datetime) -> list[Reminder]:
    cancel_pending(deadline)
    return plan_reminders(deadline, now)


def _reminders_for(deadline, user_id, schedule, planned, now) -> list[Reminder]:
    have = {offset for user, offset, type_ in planned if user == user_id and type_ == Reminder.Type.REMINDER}
    rows = [
        _row(deadline, user_id, Reminder.Type.REMINDER, offset, at)
        for offset, at in schedule
        if at > now and offset not in have
    ]
    missed = [offset for offset, at in schedule if at <= now]
    # One catch-up now instead of several stale reminders, unless a closer one already exists.
    if missed and not any(offset <= min(missed) for offset in have):
        rows.append(_row(deadline, user_id, Reminder.Type.REMINDER, min(missed), now))
    return rows


def _escalation_for(deadline, user_id, schedule, planned, now) -> list[Reminder]:
    last_offset, last_at = schedule[-1]
    if (user_id, last_offset, Reminder.Type.ESCALATION) in planned:
        return []
    send_at = local_time(last_at.date(), settings.ESCALATION_SEND_HOUR)
    if send_at <= now:
        send_at = now + timedelta(hours=1)
    return [_row(deadline, user_id, Reminder.Type.ESCALATION, last_offset, send_at)]


def _row(deadline, user_id, type_, offset, send_at) -> Reminder:
    return Reminder(
        deadline=deadline,
        recipient_id=user_id,
        type=type_,
        offset_days=offset,
        for_due_date=deadline.due_date,
        send_at=send_at,
    )
