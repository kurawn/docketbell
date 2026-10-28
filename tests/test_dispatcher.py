import threading
from datetime import timedelta

import pytest
from django.db import connection, transaction

from reminders.dispatcher import dispatch
from reminders.models import Reminder


@pytest.mark.django_db
def test_claims_due_rows_with_a_lease(make_reminder, now, settings):
    due = make_reminder(send_at=now - timedelta(minutes=1))
    later = make_reminder(send_at=now + timedelta(minutes=1))

    assert dispatch(now=now) == [due.id]

    due.refresh_from_db()
    later.refresh_from_db()
    assert due.status == "sending"
    assert due.locked_until == now + timedelta(seconds=settings.SEND_LEASE_SECONDS)
    assert later.status == "pending"


@pytest.mark.django_db
def test_reclaims_rows_whose_lease_expired(make_reminder, now):
    stuck = make_reminder(status="sending", locked_until=now - timedelta(seconds=1))
    make_reminder(status="sending", locked_until=now + timedelta(minutes=1))

    assert dispatch(now=now) == [stuck.id]


@pytest.mark.django_db
def test_respects_the_batch_size(make_reminder, now, settings):
    settings.DISPATCH_BATCH_SIZE = 2
    for _ in range(3):
        make_reminder(send_at=now - timedelta(minutes=1))

    assert len(dispatch(now=now)) == 2


@pytest.mark.django_db(transaction=True)
def test_skips_rows_locked_by_another_worker(make_reminder, now):
    reminders = [make_reminder(send_at=now - timedelta(minutes=1)) for _ in range(6)]
    locked = {r.id for r in reminders[:2]}
    seen = {}

    def other_worker():
        try:
            seen["ids"] = set(dispatch(now=now))
        finally:
            connection.close()

    with transaction.atomic():
        list(Reminder.objects.select_for_update().filter(id__in=locked))
        worker = threading.Thread(target=other_worker)
        worker.start()
        worker.join(timeout=10)
        assert not worker.is_alive(), "dispatch blocked on locked rows"

    assert seen["ids"] == {r.id for r in reminders[2:]}
