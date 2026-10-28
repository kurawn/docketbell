import json

import httpx
import pytest
import respx

from reminders.providers.base import (
    InvalidWebhook,
    OutboundMessage,
    PermanentProviderError,
    TransientProviderError,
)
from reminders.providers.sandbox import SandboxProvider
from sandbox.signing import sign

MESSAGE = OutboundMessage(to="alice@example.com", subject="s", body="b")


@pytest.fixture
def send_route(settings):
    with respx.mock:
        yield respx.post(f"{settings.SANDBOX_BASE_URL}/sandbox/v1/messages")


def test_accepted_message_returns_the_provider_id(send_route):
    send_route.mock(return_value=httpx.Response(202, json={"message_id": "m-1"}))

    assert SandboxProvider().send(MESSAGE, "key-1").provider_message_id == "m-1"
    assert send_route.calls.last.request.headers["Idempotency-Key"] == "key-1"


@pytest.mark.parametrize(
    "outcome",
    [
        httpx.Response(503),
        httpx.Response(202, text="not json"),
        httpx.ReadTimeout("slow"),
        httpx.ConnectError("down"),
    ],
)
def test_retryable_failures_are_transient(send_route, outcome):
    if isinstance(outcome, Exception):
        send_route.mock(side_effect=outcome)
    else:
        send_route.mock(return_value=outcome)

    with pytest.raises(TransientProviderError):
        SandboxProvider().send(MESSAGE, "key-1")


def test_rate_limit_carries_retry_after(send_route):
    send_route.mock(return_value=httpx.Response(429, headers={"Retry-After": "10"}))

    with pytest.raises(TransientProviderError) as error:
        SandboxProvider().send(MESSAGE, "key-1")
    assert error.value.retry_after == 10.0


@pytest.mark.parametrize("status", [400, 401, 422])
def test_client_errors_are_permanent(send_route, status):
    send_route.mock(return_value=httpx.Response(status, json={"error": "no"}))

    with pytest.raises(PermanentProviderError):
        SandboxProvider().send(MESSAGE, "key-1")


def webhook_body(**overrides):
    payload = {
        "event_id": "evt-1",
        "type": "message.delivered",
        "message_id": "m-1",
        "idempotency_key": "key-1",
        "occurred_at": "2026-06-01T08:00:00+00:00",
        "reason": "",
    }
    return json.dumps({**payload, **overrides}).encode()


def test_valid_webhook_is_parsed(settings):
    body = webhook_body()
    headers = {"X-Sandbox-Signature": sign(settings.WEBHOOK_SECRET, 1_000, body)}

    event = SandboxProvider().parse_webhook(headers, body, now=1_010)

    assert (event.event_id, event.type, event.idempotency_key) == ("evt-1", "delivered", "key-1")


@pytest.mark.parametrize(
    ("header", "now"),
    [
        ("t=1000,v1=deadbeef", 1_010),  # wrong signature
        (None, 1_000 + 301),  # correct signature, too old
        ("garbage", 1_000),  # malformed header
    ],
)
def test_bad_webhooks_are_rejected(settings, header, now):
    body = webhook_body()
    headers = {"X-Sandbox-Signature": header or sign(settings.WEBHOOK_SECRET, 1_000, body)}

    with pytest.raises(InvalidWebhook):
        SandboxProvider().parse_webhook(headers, body, now=now)


def test_unknown_event_type_is_rejected(settings):
    body = webhook_body(type="message.opened")
    headers = {"X-Sandbox-Signature": sign(settings.WEBHOOK_SECRET, 1_000, body)}

    with pytest.raises(InvalidWebhook):
        SandboxProvider().parse_webhook(headers, body, now=1_000)
