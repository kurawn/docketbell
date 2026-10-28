from rest_framework.exceptions import APIException, ValidationError
from rest_framework.views import exception_handler


class Conflict(APIException):
    status_code = 409
    default_code = "conflict"
    default_detail = "The request conflicts with the current state."


def error_handler(exc, context):
    """Wraps every DRF error in {"error": {"code", "message", "details"}}."""
    response = exception_handler(exc, context)
    if response is None:
        return None
    if isinstance(exc, ValidationError):
        code, message, details = "validation_error", "Invalid input.", response.data
    else:
        detail = response.data.get("detail", "") if isinstance(response.data, dict) else ""
        code = getattr(detail, "code", None) or getattr(exc, "default_code", "error")
        message, details = str(detail), {}
    response.data = {"error": {"code": code, "message": message, "details": details}}
    return response
