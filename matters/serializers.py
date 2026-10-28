from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import serializers

from matters.models import Deadline, Matter, MatterMember


class MemberSerializer(serializers.ModelSerializer):
    username = serializers.SlugRelatedField(
        source="user", slug_field="username", queryset=get_user_model().objects.all()
    )

    class Meta:
        model = MatterMember
        fields = ["username", "role"]


class MatterSerializer(serializers.ModelSerializer):
    members = MemberSerializer(many=True, read_only=True)

    class Meta:
        model = Matter
        fields = ["id", "reference", "title", "kind", "members", "created_at"]
        read_only_fields = ["id", "created_at"]


class DeadlineSerializer(serializers.ModelSerializer):
    reminder_offsets = serializers.ListField(
        child=serializers.IntegerField(min_value=1, max_value=60), min_length=1, max_length=5, required=False
    )
    rolled = serializers.BooleanField(read_only=True)
    acknowledged_by = serializers.SlugRelatedField(slug_field="username", read_only=True)

    class Meta:
        model = Deadline
        fields = [
            "id",
            "matter",
            "kind",
            "title",
            "nominal_date",
            "due_date",
            "rolled",
            "holiday_data_complete",
            "reminder_offsets",
            "status",
            "acknowledged_by",
            "acknowledged_at",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "matter",
            "due_date",
            "holiday_data_complete",
            "acknowledged_at",
            "created_at",
        ]

    def validate_reminder_offsets(self, value):
        if len(set(value)) != len(value):
            raise serializers.ValidationError("Offsets must be unique.")
        return sorted(value, reverse=True)

    def validate_nominal_date(self, value):
        if value < timezone.localdate():
            raise serializers.ValidationError("Must not be in the past.")
        return value

    def validate_status(self, value):
        if self.instance is None and value != Deadline.Status.OPEN:
            raise serializers.ValidationError("New deadlines are always open.")
        return value
