from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from rest_framework.authtoken.models import Token

from matters.models import Deadline, Matter, MatterMember
from matters.services import create_deadline
from workdays.holidays import get_calendar

DEMO_USERS = (("alice", "responsible"), ("bob", "assistant"), ("carol", "supervisor"), ("dave", None))
REFERENCE = "EP-2026-0142"


class Command(BaseCommand):
    help = "Create demo users, tokens and a matter with deadlines (DEBUG only, idempotent)."

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("seed_demo only runs with DEBUG on")
        users = {}
        for name, _ in DEMO_USERS:
            user, _ = get_user_model().objects.get_or_create(
                username=name, defaults={"email": f"{name}@example.com"}
            )
            Token.objects.get_or_create(user=user, defaults={"key": f"demo-{name}-token"})
            users[name] = user
        if not get_user_model().objects.filter(username="admin").exists():
            get_user_model().objects.create_superuser("admin", "admin@example.com", "admin")
        self.stdout.write("Demo tokens: " + ", ".join(f"{n}=demo-{n}-token" for n, _ in DEMO_USERS))
        if Matter.objects.filter(reference=REFERENCE).exists():
            self.stdout.write("Demo matter already present")
            return

        matter = Matter.objects.create(
            reference=REFERENCE, title="Self-cleaning solar panel coating", kind="patent"
        )
        for name, role in DEMO_USERS:
            if role:
                MatterMember.objects.create(matter=matter, user=users[name], role=role)
        today = timezone.localdate()
        create_deadline(
            matter=matter,
            kind=Deadline.Kind.OFFICE_ACTION_RESPONSE,
            title="Respond to examination report",
            nominal_date=today + timedelta(days=3),  # earlier offsets already missed: catch-up fires now
        )
        holiday = next((d for d in sorted(get_calendar().days) if d > today + timedelta(days=21)), None)
        if holiday:
            create_deadline(
                matter=matter,
                kind=Deadline.Kind.RENEWAL_FEE,
                title="Pay year-5 renewal fee",
                nominal_date=holiday,  # lands on a bank holiday, so it rolls
            )
        self.stdout.write(f"Created demo matter {REFERENCE}")
