from rest_framework.pagination import CursorPagination


class CreatedCursorPagination(CursorPagination):
    ordering = "-created_at"
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 200


class DueDateCursorPagination(CreatedCursorPagination):
    ordering = ("due_date", "id")
