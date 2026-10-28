from datetime import date, timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from matters.services import compute_due_date, create_deadline

pytestmark = pytest.mark.django_db


def upcoming(weekday: int, after_days: int = 14):
    day = timezone.localdate() + timedelta(days=after_days)
    while day.weekday() != weekday:
        day += timedelta(days=1)
    return day


def new_deadline(matter, title="Respond to examination report"):
    return create_deadline(matter=matter, kind="other", title=title, nominal_date=upcoming(2))


def test_creator_becomes_the_responsible_member(api, team):
    response = api(team.attorney).post(
        "/api/v1/matters/",
        {"reference": "GB-2026-0001", "title": "Folding bicycle hinge", "kind": "patent"},
        format="json",
    )

    assert response.status_code == 201
    assert response.json()["members"] == [{"username": "alice", "role": "responsible"}]


def test_outsider_gets_404_not_403(api, team, matter):
    deadline = new_deadline(matter)

    matter_response = api(team.outsider).get(f"/api/v1/matters/{matter.id}/")
    deadline_response = api(team.outsider).get(f"/api/v1/deadlines/{deadline.id}/")

    assert matter_response.status_code == 404
    assert matter_response.json()["error"]["code"] == "not_found"
    assert deadline_response.status_code == 404


def test_saturday_deadline_rolls_to_the_next_working_day(api, team, matter, uk_holidays):
    saturday = upcoming(5)

    response = api(team.attorney).post(
        f"/api/v1/matters/{matter.id}/deadlines/",
        {"kind": "renewal_fee", "title": "Year 5 renewal", "nominal_date": saturday.isoformat()},
        format="json",
    )

    assert response.status_code == 201
    body = response.json()
    assert body["rolled"] is True
    assert body["due_date"] >= (saturday + timedelta(days=2)).isoformat()
    assert body["reminder_offsets"] == [10, 5, 1]


def test_past_nominal_date_is_rejected(api, team, matter):
    yesterday = timezone.localdate() - timedelta(days=1)

    response = api(team.attorney).post(
        f"/api/v1/matters/{matter.id}/deadlines/",
        {"kind": "other", "title": "Too late", "nominal_date": yesterday.isoformat()},
        format="json",
    )

    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert "nominal_date" in error["details"]


def test_duplicate_offsets_are_rejected(api, team, matter):
    response = api(team.attorney).post(
        f"/api/v1/matters/{matter.id}/deadlines/",
        {"kind": "other", "title": "X", "nominal_date": upcoming(2).isoformat(), "reminder_offsets": [5, 5]},
        format="json",
    )

    assert response.status_code == 400
    assert "reminder_offsets" in response.json()["error"]["details"]


def test_assistant_cannot_edit_a_deadline(api, team, matter):
    deadline = new_deadline(matter)

    response = api(team.assistant).patch(f"/api/v1/deadlines/{deadline.id}/", {"title": "New"}, format="json")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "permission_denied"


def test_closed_deadline_cannot_change(api, team, matter):
    deadline = new_deadline(matter)
    client = api(team.attorney)
    url = f"/api/v1/deadlines/{deadline.id}/"

    assert client.patch(url, {"status": "completed"}, format="json").status_code == 200
    response = client.patch(url, {"title": "Again"}, format="json")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


def test_deadline_list_query_count_does_not_grow_with_rows(api, team, matter):
    client = api(team.attorney)

    def queries_for_list() -> int:
        with CaptureQueriesContext(connection) as ctx:
            assert client.get("/api/v1/deadlines/").status_code == 200
        return len(ctx.captured_queries)

    for i in range(2):
        new_deadline(matter, title=f"D{i}")
    few = queries_for_list()
    for i in range(6):
        new_deadline(matter, title=f"E{i}")

    assert queries_for_list() == few


def test_deadline_list_rejects_bad_filters(api, team, matter):
    client = api(team.attorney)

    assert client.get("/api/v1/deadlines/?due_before=tomorrow").status_code == 400
    assert client.get("/api/v1/deadlines/?status=lost").status_code == 400


def test_deadline_list_filters_by_due_date(api, team, matter):
    early = new_deadline(matter, title="Early")
    create_deadline(
        matter=matter, kind="other", title="Late", nominal_date=early.nominal_date + timedelta(days=60)
    )

    response = api(team.attorney).get(f"/api/v1/deadlines/?due_before={early.due_date.isoformat()}")

    assert [d["title"] for d in response.json()["results"]] == ["Early"]


def test_due_date_beyond_known_holidays_is_flagged(uk_holidays):
    due, complete = compute_due_date(date(2100, 1, 4))

    assert due == date(2100, 1, 4)
    assert complete is False


def test_add_member_by_username(api, team, matter, make_user):
    make_user("erin")
    client = api(team.attorney)
    url = f"/api/v1/matters/{matter.id}/members/"

    response = client.post(url, {"username": "erin", "role": "assistant"}, format="json")
    duplicate = client.post(url, {"username": "erin", "role": "assistant"}, format="json")

    assert response.status_code == 201
    assert response.json() == {"username": "erin", "role": "assistant"}
    assert duplicate.status_code == 400


def test_member_added_through_the_api_gets_reminders(api, team, matter, make_user, uk_holidays):
    erin = make_user("erin")
    deadline = create_deadline(
        matter=matter, kind="other", title="Renewal", nominal_date=timezone.localdate() + timedelta(days=60)
    )

    api(team.attorney).post(
        f"/api/v1/matters/{matter.id}/members/", {"username": "erin", "role": "assistant"}, format="json"
    )

    assert deadline.reminders.filter(recipient=erin, type="reminder").count() == 3
