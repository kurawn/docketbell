from django.contrib import admin

from core.admin import ReadOnlyAdmin
from workdays.models import BankHoliday


@admin.register(BankHoliday)
class BankHolidayAdmin(ReadOnlyAdmin):
    """Loaded from GOV.UK; a manual edit would not re-roll open deadlines."""

    list_display = ["date", "title", "region"]
    list_filter = ["region"]
    date_hierarchy = "date"
