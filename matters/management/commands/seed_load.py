from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import connection
from django.utils import timezone

from matters.models import Deadline, Matter
from reminders.models import Reminder

PER_DEADLINE = 5


class Command(BaseCommand):
    help = "Seed many reminders and print EXPLAIN ANALYZE for the dispatcher's due-reminder query."

    def add_arguments(self, parser):
        parser.add_argument("--count", type=int, default=100_000)

    def handle(self, *args, count, **options):
        now = timezone.now()
        user, _ = get_user_model().objects.get_or_create(username="loadtest", defaults={"email": ""})
        matter, _ = Matter.objects.get_or_create(
            reference="LOAD-0001", defaults={"title": "Load", "kind": "patent"}
        )
        # Completed deadlines: any pending rows the live stack picks up are cancelled without sending.
        deadlines = Deadline.objects.bulk_create(
            [
                Deadline(
                    matter=matter,
                    kind="other",
                    title=f"Load {i}",
                    nominal_date=now.date(),
                    due_date=now.date(),
                    status="completed",
                )
                for i in range(count // PER_DEADLINE)
            ],
            batch_size=5000,
        )
        reminders = [
            Reminder(
                deadline=deadline,
                recipient=user,
                offset_days=offset,
                for_due_date=deadline.due_date,
                send_at=now + timedelta(minutes=(i % 600) - 300),
                status="pending" if (i * PER_DEADLINE + offset) % 20 == 0 else "delivered",
            )
            for i, deadline in enumerate(deadlines)
            for offset in range(1, PER_DEADLINE + 1)
        ]
        Reminder.objects.bulk_create(reminders, batch_size=5000)
        with connection.cursor() as cursor:
            cursor.execute("ANALYZE reminders_reminder")
        due = Reminder.objects.filter(status="pending", send_at__lte=now).order_by("send_at")
        self.stdout.write(due[: settings.DISPATCH_BATCH_SIZE].explain(analyze=True))
