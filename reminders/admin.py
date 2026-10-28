from django.contrib import admin

from core.admin import ReadOnlyAdmin
from reminders.models import Reminder, WebhookEvent


@admin.register(Reminder)
class ReminderAdmin(ReadOnlyAdmin):
    list_display = [
        "deadline", "recipient", "type", "offset_days", "send_at", "status", "attempts", "sent_at"
    ]
    list_filter = ["status", "type"]
    list_select_related = ["deadline", "recipient"]
    search_fields = [
        "deadline__title", "deadline__matter__reference", "recipient__username", "=idempotency_key"
    ]
    date_hierarchy = "send_at"


@admin.register(WebhookEvent)
class WebhookEventAdmin(ReadOnlyAdmin):
    list_display = ["event_id", "type", "reminder", "created_at"]
    list_filter = ["type"]
    search_fields = ["=event_id"]
