from reminders.models import Reminder
from reminders.providers.base import OutboundMessage


def compose(reminder: Reminder) -> OutboundMessage:
    deadline = reminder.deadline
    matter = deadline.matter
    due = f"{deadline.due_date:%A %d %B %Y}"
    prefix = "[Not acknowledged] " if reminder.type == Reminder.Type.ESCALATION else ""
    lines = [f"Matter: {matter.reference} ({matter.title})", f"Deadline: {deadline.title}", f"Due: {due}"]
    if deadline.rolled:
        lines.append(f"Moved from {deadline.nominal_date:%d %B %Y}, which is not a working day.")
    lines.append(f"Acknowledge: POST /api/v1/deadlines/{deadline.id}/acknowledge/")
    return OutboundMessage(
        to=reminder.recipient.email,
        subject=f"{prefix}{matter.reference}: {deadline.title} due {due}",
        body="\n".join(lines),
    )
