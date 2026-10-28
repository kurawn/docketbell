"""Matter and deadline admin. Every save that affects reminders goes through matters.services."""

from django import forms
from django.contrib import admin, messages
from django.utils import timezone
from unfold.admin import ModelAdmin, TabularInline

from matters import services
from matters.models import Deadline, Matter, MatterMember
from reminders.models import Reminder

DEADLINE_EDITABLE = ("kind", "title", "nominal_date", "reminder_offsets", "status")


class MemberInline(TabularInline):
    """Members can be added (which plans their reminders) but not changed or removed, as in the API."""

    model = MatterMember
    extra = 0
    can_delete = False
    autocomplete_fields = ["user"]

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Matter)
class MatterAdmin(ModelAdmin):
    list_display = ["reference", "title", "kind", "created_at"]
    list_filter = ["kind"]
    search_fields = ["reference", "title"]
    inlines = [MemberInline]

    def has_delete_permission(self, request, obj=None):
        return False  # would cascade to deadlines and their reminder history

    def save_formset(self, request, form, formset, change):
        if formset.model is not MatterMember:
            return super().save_formset(request, form, formset, change)
        for member in formset.save(commit=False):  # only new rows: existing ones are read-only
            services.add_member(matter=member.matter, user=member.user, role=member.role)


class DeadlineForm(forms.ModelForm):
    """Same rules as DeadlineSerializer."""

    class Meta:
        model = Deadline
        fields = ["matter", *DEADLINE_EDITABLE]

    def clean_reminder_offsets(self):
        offsets = self.cleaned_data["reminder_offsets"]
        if not 1 <= len(offsets) <= 5:
            raise forms.ValidationError("Give between 1 and 5 offsets.")
        if any(not 1 <= offset <= 60 for offset in offsets):
            raise forms.ValidationError("Each offset must be between 1 and 60 working days.")
        if len(set(offsets)) != len(offsets):
            raise forms.ValidationError("Offsets must be unique.")
        return sorted(offsets, reverse=True)

    def clean_nominal_date(self):
        value = self.cleaned_data["nominal_date"]
        if "nominal_date" in self.changed_data and value < timezone.localdate():
            raise forms.ValidationError("Must not be in the past.")
        return value

    def clean_status(self):
        value = self.cleaned_data["status"]
        if self.instance._state.adding and value != Deadline.Status.OPEN:
            raise forms.ValidationError("New deadlines are always open.")
        return value


class ReminderInline(TabularInline):
    model = Reminder
    extra = 0
    can_delete = False
    ordering = ["send_at", "type"]
    fields = [
        "recipient", "type", "offset_days", "for_due_date", "send_at", "status", "attempts", "last_error"
    ]
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Deadline)
class DeadlineAdmin(ModelAdmin):
    form = DeadlineForm
    list_display = ["title", "matter", "kind", "nominal_date", "due_date", "status", "acknowledged_by"]
    list_filter = ["status", "kind", "holiday_data_complete"]
    list_select_related = ["matter", "acknowledged_by"]
    search_fields = ["title", "matter__reference"]
    date_hierarchy = "due_date"
    autocomplete_fields = ["matter"]
    inlines = [ReminderInline]
    actions = ["mark_completed", "mark_cancelled"]

    def get_readonly_fields(self, request, obj=None):
        computed = ["due_date", "holiday_data_complete", "acknowledged_by", "acknowledged_at"]
        if obj is None:
            return computed
        if obj.status != Deadline.Status.OPEN:
            return ["matter", *DEADLINE_EDITABLE, *computed]  # closed deadlines never change
        return ["matter", *computed]

    def save_model(self, request, obj, form, change):
        if change:
            changes = {field: form.cleaned_data[field] for field in form.changed_data}
            if changes:
                services.update_deadline(obj.pk, changes)
            return
        obj.pk = services.create_deadline(
            matter=obj.matter,
            kind=obj.kind,
            title=obj.title,
            nominal_date=obj.nominal_date,
            reminder_offsets=obj.reminder_offsets,
        ).pk
        obj.refresh_from_db()

    def has_delete_permission(self, request, obj=None):
        return False  # deleting would silently drop reminder history; cancel instead

    @admin.action(description="Mark selected deadlines completed")
    def mark_completed(self, request, queryset):
        self._close(request, queryset, Deadline.Status.COMPLETED)

    @admin.action(description="Cancel selected deadlines")
    def mark_cancelled(self, request, queryset):
        self._close(request, queryset, Deadline.Status.CANCELLED)

    def _close(self, request, queryset, status):
        ids = list(queryset.values_list("id", flat=True))
        closed = 0
        for deadline_id in ids:
            try:
                services.update_deadline(deadline_id, {"status": status})
                closed += 1
            except services.DeadlineClosed:
                pass
        self.message_user(request, f"{closed} deadline(s) set to {status}; pending reminders cancelled.")
        if closed < len(ids):
            self.message_user(request, "Already closed deadlines were skipped.", messages.WARNING)
