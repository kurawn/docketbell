from django.contrib import admin

from core.admin import ReadOnlyAdmin
from sandbox.models import SandboxMessage


@admin.register(SandboxMessage)
class SandboxMessageAdmin(ReadOnlyAdmin):
    list_display = ["to", "subject", "status", "created_at"]
    list_filter = ["status"]
    search_fields = ["to", "subject", "=idempotency_key"]
