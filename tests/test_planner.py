from datetime import UTC, date, datetime

import pytest

from matters.services import add_member, create_deadline, update_deadline
from reminders.planner import plan_reminders

pytestmark = pytest.mark.django_db


def utc(*args):
    return datetime(*args, tzinfo=UTC)


def live_schedule(deadline):
    rows = deadline.reminders.exclude(status="cancelled").select_related("recipient")
    return sorted((r.recipient.username, r.type, r.offset_days, r.send_at) for r in rows)


def test_default_offsets_give_three_reminders_each_and_one_escalation(deadline):
    assert deadline.due_date == date(2026, 6, 15)  # Saturday 13 June rolls to Monday

    assert live_schedule(deadline) == sorted(
        [
            ("alice", "reminder", 10, utc(2026, 6, 1, 8)),  # 09:00 BST
            ("alice", "reminder", 5, utc(2026, 6, 8, 8)),
            ("alice", "reminder", 1, utc(2026, 6, 12, 8)),
            ("bob", "reminder", 10, utc(2026, 6, 1, 8)),
            ("bob", "reminder", 5, utc(2026, 6, 8, 8)),
            ("bob", "reminder", 1, utc(2026, 6, 12, 8)),
            ("carol", "escalation", 1, utc(2026, 6, 12, 14)),  # 15:00 BST
        ]
    )


def test_missed_offsets_collapse_into_one_catch_up(matter, uk_holidays):
    late = utc(2026, 6, 9, 10)

    deadline = create_deadline(
        matter=matter, kind="other", title="Entered late", nominal_date=date(2026, 6, 13), now=late
    )

    assert live_schedule(deadline) == sorted(
        [
            ("alice", "reminder", 5, late),
            ("alice", "reminder", 1, utc(2026, 6, 12, 8)),
            ("bob", "reminder", 5, late),
            ("bob", "reminder", 1, utc(2026, 6, 12, 8)),
            ("carol", "escalation", 1, utc(2026, 6, 12, 14)),
        ]
    )


def test_planning_again_after_a_catch_up_adds_nothing(matter, uk_holidays):
    late = utc(2026, 6, 9, 10)
    deadline = create_deadline(
        matter=matter, kind="other", title="Entered late", nominal_date=date(2026, 6, 13), now=late
    )

    assert plan_reminders(deadline, late) == []


def test_send_times_follow_uk_clock_changes(matter, uk_holidays):
    deadline = create_deadline(
        matter=matter,
        kind="other",
        title="Across the clock change",
        nominal_date=date(2026, 3, 31),
        reminder_offsets=[2, 1],
        now=utc(2026, 3, 1),
    )

    alice = [row for row in live_schedule(deadline) if row[0] == "alice"]
    assert alice == [
        ("alice", "reminder", 1, utc(2026, 3, 30, 8)),  # Monday, BST
        ("alice", "reminder", 2, utc(2026, 3, 27, 9)),  # Friday, GMT
    ]


def test_planning_twice_creates_nothing(deadline, now):
    assert plan_reminders(deadline, now) == []


def test_moving_the_date_cancels_pending_and_replans(deadline, now):
    update_deadline(deadline.pk, {"nominal_date": date(2026, 6, 20)}, now=now)

    deadline.refresh_from_db()
    assert deadline.due_date == date(2026, 6, 22)
    assert deadline.reminders.filter(status="cancelled").count() == 7
    live = deadline.reminders.exclude(status="cancelled")
    assert live.count() == 7
    assert set(live.values_list("for_due_date", flat=True)) == {date(2026, 6, 22)}


def test_changing_offsets_does_not_resend_delivered_reminders(deadline, team, now):
    deadline.reminders.filter(recipient=team.attorney, offset_days=10).update(status="delivered")

    update_deadline(deadline.pk, {"reminder_offsets": [10, 5, 2]}, now=now)

    live = deadline.reminders.exclude(status="cancelled")
    assert list(live.filter(recipient=team.attorney, offset_days=10).values_list("status", flat=True)) == [
        "delivered"
    ]
    assert live.filter(type="reminder", offset_days=2).count() == 2
    assert live.get(type="escalation").offset_days == 2


def test_completing_a_deadline_cancels_pending_reminders(deadline, now):
    update_deadline(deadline.pk, {"status": "completed"}, now=now)

    assert not deadline.reminders.filter(status="pending").exists()


def test_new_member_gets_reminders_for_open_deadlines(deadline, make_user, now):
    erin = make_user("erin")

    add_member(matter=deadline.matter, user=erin, role="assistant", now=now)

    assert deadline.reminders.filter(recipient=erin, type="reminder").count() == 3


def test_new_member_gets_one_catch_up_for_missed_offsets(deadline, make_user):
    erin = make_user("erin")
    later = utc(2026, 6, 9, 10)

    add_member(matter=deadline.matter, user=erin, role="assistant", now=later)

    assert sorted(deadline.reminders.filter(recipient=erin).values_list("offset_days", "send_at")) == [
        (1, utc(2026, 6, 12, 8)),
        (5, later),
    ]


def test_reminders_endpoint_lists_the_schedule(api, team, deadline):
    response = api(team.attorney).get(f"/api/v1/deadlines/{deadline.id}/reminders/")

    assert response.status_code == 200
    assert len(response.json()) == 7
    assert response.json()[0]["status"] == "pending"
    assert api(team.outsider).get(f"/api/v1/deadlines/{deadline.id}/reminders/").status_code == 404

