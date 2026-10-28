from django.db import DatabaseError, connection
from django.http import JsonResponse


def healthz(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except DatabaseError:
        return JsonResponse({"status": "unavailable"}, status=503)
    return JsonResponse({"status": "ok"})


def not_found(request, exception=None):
    return JsonResponse({"error": {"code": "not_found", "message": "Not found.", "details": {}}}, status=404)


def server_error(request):
    body = {"error": {"code": "server_error", "message": "Something went wrong.", "details": {}}}
    return JsonResponse(body, status=500)
