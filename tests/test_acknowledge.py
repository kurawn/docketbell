import pytest

from matters.services import update_deadline

pytestmark = pytest.mark.django_db


def url(deadline):
    return f"/api/v1/deadlines/{deadline.id}/acknowledge/"


def test_acknowledging_cancels_only_the_escalation(api, team, deadline):
    response = api(team.assistant).post(url(deadline))

    assert response.status_code == 200
    assert response.json()["acknowledged_by"] == "bob"
    assert deadline.reminders.get(type="escalation").status == "cancelled"
    assert deadline.reminders.filter(type="reminder", status="pending").count() == 6


def test_first_acknowledgement_wins_and_repeats_are_harmless(api, team, deadline):
    api(team.assistant).post(url(deadline))

    response = api(team.attorney).post(url(deadline))

    assert response.status_code == 200
    assert response.json()["acknowledged_by"] == "bob"


def test_supervisor_cannot_acknowledge(api, team, deadline):
    assert api(team.supervisor).post(url(deadline)).status_code == 403


def test_outsider_gets_404(api, team, deadline):
    assert api(team.outsider).post(url(deadline)).status_code == 404


def test_closed_deadline_cannot_be_acknowledged(api, team, deadline, now):
    update_deadline(deadline.pk, {"status": "completed"}, now=now)

    response = api(team.attorney).post(url(deadline))

    assert response.status_code == 409
