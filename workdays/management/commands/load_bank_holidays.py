import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from workdays.holidays import parse_events, upsert_holidays

SNAPSHOT = Path(__file__).resolve().parents[2] / "data" / "bank-holidays.json"


class Command(BaseCommand):
    help = "Load UK bank holidays from the bundled GOV.UK snapshot."

    def handle(self, *args, **options):
        region = settings.BANK_HOLIDAY_REGION
        added = upsert_holidays(region, parse_events(json.loads(SNAPSHOT.read_text()), region))
        self.stdout.write(f"{len(added)} new bank holidays loaded for {region}")
