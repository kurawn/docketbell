from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.utils import timezone

from matters.models import Deadline, MatterMember
from matters.services import create_deadline
from reminders.models import Reminder

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin_client():
    client = Client()
    client.force_login(get_user_model().objects.create_superuser("root", "root@example.com", "pw"))
    return client


@pytest.fixture
def future_deadline(matter, uk_holidays):
    return create_deadline(
        matter=matter,
        kind="other",
        title="Admin test",
        nominal_date=timezone.localdate() + timedelta(days=40),
    )


def live(deadline):
    return deadline.reminders.exclude(status=Reminder.Status.CANCELLED)


def deadline_form(deadline, **overrides):
    data = {
        "kind": deadline.kind,
        "title": deadline.title,
        "nominal_date": deadline.nominal_date.isoformat(),
        "reminder_offsets": ",".join(map(str, deadline.reminder_offsets)),
        "status": deadline.status,
        "reminders-TOTAL_FORMS": "0",
        "reminders-INITIAL_FORMS": "0",
    }
    return data | overrides


def test_every_admin_page_renders(admin_client, future_deadline):
    for url in ["/admin/", "/admin/matters/matter/", "/admin/matters/deadline/", "/admin/reminders/reminder/",
                "/admin/reminders/webhookevent/", "/admin/workdays/bankholiday/",
                "/admin/sandbox/sandboxmessage/", "/admin/matters/deadline/add/",
                "/admin/auth/user/", "/admin/auth/user/add/", "/admin/auth/group/",
                "/admin/authtoken/tokenproxy/", "/admin/matters/matter/add/",
                f"/admin/matters/deadline/{future_deadline.pk}/change/",
                f"/admin/matters/matter/{future_deadline.matter_id}/change/"]:
        assert admin_client.get(url).status_code == 200, url


def test_admin_requires_staff(client, team):
    client.force_login(team.attorney)

    assert client.get("/admin/").status_code == 302


def test_adding_a_deadline_rolls_the_date_and_plans_reminders(admin_client, matter, uk_holidays):
    saturday = timezone.localdate() + timedelta(days=40)
    saturday += timedelta(days=(5 - saturday.weekday()) % 7)

    response = admin_client.post(
        "/admin/matters/deadline/add/",
        {"matter": matter.pk, "kind": "other", "title": "Via admin", "nominal_date": saturday.isoformat(),
         "reminder_offsets": "5,10", "status": "open",
         "reminders-TOTAL_FORMS": "0", "reminders-INITIAL_FORMS": "0"},
    )

    assert response.status_code == 302
    deadline = Deadline.objects.get(title="Via admin")
    assert deadline.due_date > saturday
    assert deadline.reminder_offsets == [10, 5]
    assert live(deadline).filter(type=Reminder.Type.REMINDER).count() == 4  # alice and bob, two offsets each


def test_admin_rejects_what_the_api_rejects(admin_client, future_deadline):
    url = f"/admin/matters/deadline/{future_deadline.pk}/change/"

    for overrides in [{"reminder_offsets": "5,5"}, {"reminder_offsets": "0"},
                      {"nominal_date": (timezone.localdate() - timedelta(days=1)).isoformat()}]:
        response = admin_client.post(url, deadline_form(future_deadline, **overrides))
        assert response.status_code == 200, overrides  # form re-rendered with errors

    future_deadline.refresh_from_db()
    assert future_deadline.reminder_offsets == [10, 5, 1]


def test_moving_a_deadline_replans(admin_client, future_deadline):
    old = set(live(future_deadline).values_list("pk", flat=True))
    new_date = future_deadline.nominal_date + timedelta(days=7)

    response = admin_client.post(
        f"/admin/matters/deadline/{future_deadline.pk}/change/",
        deadline_form(future_deadline, nominal_date=new_date.isoformat()),
    )

    assert response.status_code == 302
    future_deadline.refresh_from_db()
    assert future_deadline.nominal_date == new_date
    assert not old & set(live(future_deadline).values_list("pk", flat=True))
    assert set(live(future_deadline).values_list("for_due_date", flat=True)) == {future_deadline.due_date}


def test_complete_action_cancels_pending_reminders(admin_client, future_deadline):
    response = admin_client.post(
        "/admin/matters/deadline/",
        {"action": "mark_completed", "_selected_action": [future_deadline.pk]},
    )

    assert response.status_code == 302
    future_deadline.refresh_from_db()
    assert future_deadline.status == Deadline.Status.COMPLETED
    assert not future_deadline.reminders.filter(status=Reminder.Status.PENDING).exists()


def test_adding_a_member_plans_their_reminders(admin_client, future_deadline, team):
    matter = future_deadline.matter

    response = admin_client.post(
        f"/admin/matters/matter/{matter.pk}/change/",
        {"reference": matter.reference, "title": matter.title, "kind": matter.kind,
         "members-TOTAL_FORMS": "4", "members-INITIAL_FORMS": "3",
         **{f"members-{i}-id": m.pk for i, m in enumerate(matter.members.order_by("created_at"))},
         **{f"members-{i}-matter": matter.pk for i in range(4)},
         "members-3-user": team.outsider.pk, "members-3-role": "assistant"},
    )

    assert response.status_code == 302
    assert MatterMember.objects.filter(matter=matter, user=team.outsider).exists()
    assert live(future_deadline).filter(recipient=team.outsider).count() == 3


def test_reminders_are_read_only(admin_client, future_deadline):
    reminder = live(future_deadline).first()

    assert admin_client.get("/admin/reminders/reminder/add/").status_code == 403
    response = admin_client.post(f"/admin/reminders/reminder/{reminder.pk}/change/", {"status": "failed"})
    assert response.status_code == 403
    reminder.refresh_from_db()
    assert reminder.status == Reminder.Status.PENDING
