import hashlib
import hmac
import json
import time
from collections.abc import Mapping

import httpx
from django.conf import settings

from reminders.providers.base import (
    DeliveryEvent,
    InvalidWebhook,
    OutboundMessage,
    PermanentProviderError,
    SendResult,
    TransientProviderError,
)

WEBHOOK_TOLERANCE_SECONDS = 300
EVENT_TYPES = {"message.delivered": DeliveryEvent.DELIVERED, "message.failed": DeliveryEvent.FAILED}


class SandboxProvider:
    def __init__(self, client: httpx.Client | None = None):
        self._client = client or httpx.Client(
            base_url=settings.SANDBOX_BASE_URL,
            timeout=httpx.Timeout(5.0, connect=2.0),
            headers={"Authorization": f"Bearer {settings.SANDBOX_API_KEY}"},
        )

    def send(self, message: OutboundMessage, idempotency_key: str) -> SendResult:
        try:
            response = self._client.post(
                "/sandbox/v1/messages",
                json={"to": message.to, "subject": message.subject, "body": message.body},
                headers={"Idempotency-Key": idempotency_key},
            )
        except httpx.TransportError as exc:  # includes timeouts
            raise TransientProviderError(f"{type(exc).__name__}: {exc}") from exc
        if response.status_code == 429:
            raise TransientProviderError("rate limited", retry_after=_retry_after(response))
        if response.status_code >= 500:
            raise TransientProviderError(f"provider error {response.status_code}")
        if response.status_code >= 400:
            raise PermanentProviderError(f"rejected {response.status_code}: {response.text[:200]}")
        try:
            return SendResult(provider_message_id=str(response.json()["message_id"]))
        except (ValueError, KeyError) as exc:
            raise TransientProviderError("unreadable provider response") from exc

    def parse_webhook(
        self, headers: Mapping[str, str], body: bytes, now: float | None = None
    ) -> DeliveryEvent:
        parts = dict(
            part.split("=", 1) for part in headers.get("X-Sandbox-Signature", "").split(",") if "=" in part
        )
        try:
            timestamp, signature = int(parts["t"]), parts["v1"]
        except (KeyError, ValueError) as exc:
            raise InvalidWebhook("malformed signature header") from exc
        if abs((time.time() if now is None else now) - timestamp) > WEBHOOK_TOLERANCE_SECONDS:
            raise InvalidWebhook("timestamp outside tolerance")
        expected = hmac.new(
            settings.WEBHOOK_SECRET.encode(), f"{timestamp}.".encode() + body, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected.encode(), signature.encode()):
            raise InvalidWebhook("bad signature")
        try:
            data = json.loads(body)
            return DeliveryEvent(
                event_id=str(data["event_id"]),
                type=EVENT_TYPES[data["type"]],
                idempotency_key=str(data["idempotency_key"]),
                provider_message_id=str(data["message_id"]),
                reason=str(data.get("reason", "")),
            )
        except (ValueError, KeyError, TypeError) as exc:
            raise InvalidWebhook("unreadable payload") from exc


def _retry_after(response: httpx.Response) -> float | None:
    try:
        return float(response.headers["Retry-After"])
    except (KeyError, ValueError):
        return None
