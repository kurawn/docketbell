import pytest
from rest_framework.exceptions import NotFound, ValidationError

from core.exceptions import Conflict, error_handler


def test_validation_errors_use_the_shared_shape():
    response = error_handler(ValidationError({"title": ["This field is required."]}), {})

    assert response.status_code == 400
    assert response.data == {
        "error": {
            "code": "validation_error",
            "message": "Invalid input.",
            "details": {"title": ["This field is required."]},
        }
    }


def test_other_api_errors_use_the_shared_shape():
    response = error_handler(NotFound(), {})

    assert response.status_code == 404
    assert response.data == {"error": {"code": "not_found", "message": "Not found.", "details": {}}}


def test_conflict_is_409():
    response = error_handler(Conflict("Deadline is closed."), {})

    assert response.status_code == 409
    assert response.data["error"] == {"code": "conflict", "message": "Deadline is closed.", "details": {}}


@pytest.mark.django_db
def test_healthz_reports_ok(client):
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
