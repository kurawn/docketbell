from datetime import date

from django.db import transaction
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from core.exceptions import Conflict
from core.pagination import DueDateCursorPagination
from matters import services
from matters.models import EDITOR_ROLES, REMINDER_ROLES, Deadline, Matter, MatterMember
from matters.serializers import DeadlineSerializer, MatterSerializer, MemberSerializer
from reminders.serializers import ReminderSerializer


def require_role(user, matter, roles) -> None:
    role = MatterMember.objects.filter(matter=matter, user=user).values_list("role", flat=True).first()
    if role not in roles:
        raise PermissionDenied("Your role on this matter does not allow this.")


class MatterViewSet(
    mixins.CreateModelMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    serializer_class = MatterSerializer

    def get_queryset(self):
        return Matter.objects.filter(members__user=self.request.user).prefetch_related("members__user")

    def perform_create(self, serializer):
        with transaction.atomic():
            matter = serializer.save()
            services.add_member(matter=matter, user=self.request.user, role=MatterMember.Role.RESPONSIBLE)

    @action(detail=True, methods=["post"])
    def members(self, request, pk=None):
        matter = self.get_object()
        require_role(request.user, matter, EDITOR_ROLES)
        serializer = MemberSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]
        if matter.members.filter(user=user).exists():
            raise ValidationError({"username": ["Already a member of this matter."]})
        member = services.add_member(matter=matter, user=user, role=serializer.validated_data["role"])
        return Response(MemberSerializer(member).data, status=201)

    @action(detail=True, methods=["get", "post"])
    def deadlines(self, request, pk=None):
        matter = self.get_object()
        if request.method == "GET":
            paginator = DueDateCursorPagination()
            page = paginator.paginate_queryset(
                matter.deadlines.select_related("acknowledged_by"), request, view=self
            )
            return paginator.get_paginated_response(DeadlineSerializer(page, many=True).data)
        require_role(request.user, matter, EDITOR_ROLES)
        serializer = DeadlineSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        deadline = services.create_deadline(
            matter=matter,
            kind=data["kind"],
            title=data["title"],
            nominal_date=data["nominal_date"],
            reminder_offsets=data.get("reminder_offsets"),
        )
        return Response(DeadlineSerializer(deadline).data, status=201)


class DeadlineViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet
):
    serializer_class = DeadlineSerializer
    pagination_class = DueDateCursorPagination
    http_method_names = ["get", "patch", "post"]

    def get_queryset(self):
        deadlines = Deadline.objects.filter(matter__members__user=self.request.user).select_related(
            "matter", "acknowledged_by"
        )
        params = self.request.query_params
        if status := params.get("status"):
            if status not in Deadline.Status.values:
                raise ValidationError({"status": [f"Use one of {', '.join(Deadline.Status.values)}."]})
            deadlines = deadlines.filter(status=status)
        for param, lookup in (("due_before", "due_date__lte"), ("due_after", "due_date__gte")):
            if value := params.get(param):
                try:
                    deadlines = deadlines.filter(**{lookup: date.fromisoformat(value)})
                except ValueError:
                    raise ValidationError({param: ["Use YYYY-MM-DD."]}) from None
        return deadlines

    def perform_update(self, serializer):
        require_role(self.request.user, serializer.instance.matter, EDITOR_ROLES)
        try:
            serializer.instance = services.update_deadline(serializer.instance.pk, serializer.validated_data)
        except services.DeadlineClosed:
            raise Conflict("Deadline is closed and can no longer change.") from None

    @action(detail=True, methods=["get"])
    def reminders(self, request, pk=None):
        deadline = self.get_object()
        rows = deadline.reminders.select_related("recipient").order_by("send_at", "type")
        return Response(ReminderSerializer(rows, many=True).data)

    @action(detail=True, methods=["post"])
    def acknowledge(self, request, pk=None):
        deadline = self.get_object()
        require_role(request.user, deadline.matter, REMINDER_ROLES)
        try:
            deadline = services.acknowledge_deadline(deadline.pk, request.user)
        except services.DeadlineClosed:
            raise Conflict("Deadline is closed.") from None
        return Response(DeadlineSerializer(deadline).data)
