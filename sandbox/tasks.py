import json
import random
import time

import httpx
from celery import shared_task
from django.conf import settings

from sandbox.models import SandboxMessage
from sandbox.signing import sign


@shared_task(bind=True, name="sandbox.deliver_status_webhook", max_retries=5)
def deliver_status_webhook(self, message_id: str) -> None:
    message = SandboxMessage.objects.get(pk=message_id)
    if message.status == SandboxMessage.Status.ACCEPTED:
        failed = random.random() < settings.SANDBOX_DELIVERY_FAIL_RATE
        message.status = SandboxMessage.Status.FAILED if failed else SandboxMessage.Status.DELIVERED
        message.save(update_fields=["status", "updated_at"])
    body = json.dumps(
        {
            "event_id": f"evt_{message.id}_{message.status}",  # stable across retries
            "type": f"message.{message.status}",
            "message_id": str(message.id),
            "idempotency_key": message.idempotency_key,
            "occurred_at": message.updated_at.isoformat(),
            "reason": "mailbox unavailable" if message.status == SandboxMessage.Status.FAILED else "",
        }
    ).encode()
    headers = {
        "Content-Type": "application/json",
        "X-Sandbox-Signature": sign(settings.WEBHOOK_SECRET, int(time.time()), body),
    }
    try:
        response = httpx.post(settings.SANDBOX_WEBHOOK_URL, content=body, headers=headers, timeout=5.0)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise self.retry(exc=exc, countdown=5 * 2**self.request.retries) from exc
