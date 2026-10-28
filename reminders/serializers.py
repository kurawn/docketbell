from rest_framework import serializers

from reminders.models import Reminder


class ReminderSerializer(serializers.ModelSerializer):
    recipient = serializers.SlugRelatedField(slug_field="username", read_only=True)

    class Meta:
        model = Reminder
        fields = [
            "id",
            "type",
            "recipient",
            "offset_days",
            "for_due_date",
            "send_at",
            "status",
            "attempts",
            "last_error",
            "sent_at",
            "delivered_at",
        ]
        read_only_fields = fields
