from celery import shared_task

from reminders.dispatcher import dispatch
from reminders.sending import send_reminder


@shared_task(name="reminders.send_reminder")
def send_reminder_task(reminder_id: str) -> str:
    return send_reminder(reminder_id)


@shared_task(name="reminders.dispatch_due_reminders")
def dispatch_due_reminders() -> int:
    return len(dispatch())
