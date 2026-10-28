"""A fake messaging provider: idempotent, and unreliable on purpose."""

import hashlib
import hmac
import json
import random
import time

from django.conf import settings
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from sandbox.models import SandboxMessage
from sandbox.tasks import deliver_status_webhook


@csrf_exempt  # bearer-key API, no cookies
@require_http_methods(["GET", "POST"])
def messages(request):
    expected = f"Bearer {settings.SANDBOX_API_KEY}"
    if not hmac.compare_digest(request.headers.get("Authorization", ""), expected):
        return _error("unauthorised", 401)
    if request.method == "GET":
        rows = SandboxMessage.objects.order_by("-created_at")[:500]
        return JsonResponse({"messages": [_as_json(m) for m in rows]})
    return _create(request)


def _create(request):
    key = request.headers.get("Idempotency-Key", "").strip()
    if not key or len(key) > 100:
        return _error("Idempotency-Key header is required", 400)
    try:
        data = json.loads(request.body)
        fields = {"to": str(data["to"]), "subject": str(data["subject"]), "body": str(data["body"])}
    except (ValueError, KeyError, TypeError):
        return _error("to, subject and body are required", 400)
    request_hash = hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest()

    existing = SandboxMessage.objects.filter(idempotency_key=key).first()
    if existing:
        return _replay(existing, request_hash)

    fault = _pick_fault()
    if fault == "unavailable":
        return _error("temporarily unavailable", 503)
    if fault == "rate_limited":
        response = _error("rate limited", 429)
        response["Retry-After"] = "10"
        return response

    try:
        with transaction.atomic():
            message = SandboxMessage.objects.create(idempotency_key=key, request_hash=request_hash, **fields)
    except IntegrityError:  # a concurrent request with the same key won
        return _replay(SandboxMessage.objects.get(idempotency_key=key), request_hash)
    deliver_status_webhook.apply_async((str(message.id),), countdown=random.uniform(1, 5))
    if fault == "slow":
        time.sleep(settings.SANDBOX_SLOW_SECONDS)
    return JsonResponse({"message_id": str(message.id)}, status=202)


def _replay(message: SandboxMessage, request_hash: str):
    if message.request_hash != request_hash:
        return _error("Idempotency-Key reused with a different request", 422)
    return JsonResponse({"message_id": str(message.id)}, status=202)


def _pick_fault() -> str | None:
    roll = random.random()
    for name, rate in (
        ("unavailable", settings.SANDBOX_FAIL_RATE),
        ("rate_limited", settings.SANDBOX_RATE_LIMIT_RATE),
        ("slow", settings.SANDBOX_SLOW_RATE),
    ):
        if roll < rate:
            return name
        roll -= rate
    return None


def _error(message: str, status: int):
    return JsonResponse({"error": message}, status=status)


def _as_json(message: SandboxMessage) -> dict:
    return {
        "message_id": str(message.id),
        "idempotency_key": message.idempotency_key,
        "to": message.to,
        "subject": message.subject,
        "status": message.status,
        "created_at": message.created_at.isoformat(),
    }
