import json

import httpx
import pytest
import respx

from sandbox.models import SandboxMessage
from sandbox.signing import sign
from sandbox.tasks import deliver_status_webhook

pytestmark = [pytest.mark.django_db, pytest.mark.urls("config.urls_sandbox")]

URL = "/sandbox/v1/messages"
MESSAGE = {"to": "alice@example.com", "subject": "EP-2026-0142: respond", "body": "Due Monday"}


def post(client, settings, key="key-1", body=MESSAGE, auth=None):
    headers = {"Authorization": auth or f"Bearer {settings.SANDBOX_API_KEY}"}
    if key is not None:
        headers["Idempotency-Key"] = key
    return client.post(URL, data=json.dumps(body), content_type="application/json", headers=headers)


def test_rejects_a_wrong_api_key(client, settings):
    assert post(client, settings, auth="Bearer nope").status_code == 401


def test_requires_an_idempotency_key(client, settings):
    assert post(client, settings, key=None).status_code == 400


def test_accepts_and_stores_a_message(client, settings):
    response = post(client, settings)

    assert response.status_code == 202
    assert response.json()["message_id"] == str(SandboxMessage.objects.get().id)


def test_same_key_and_body_returns_the_original(client, settings):
    first = post(client, settings).json()
    second = post(client, settings).json()

    assert first == second
    assert SandboxMessage.objects.count() == 1


def test_same_key_with_a_different_body_is_rejected(client, settings):
    post(client, settings)

    response = post(client, settings, body={**MESSAGE, "body": "changed"})

    assert response.status_code == 422


def test_injected_outage_stores_nothing(client, settings):
    settings.SANDBOX_FAIL_RATE = 1.0

    assert post(client, settings).status_code == 503
    assert not SandboxMessage.objects.exists()


def test_injected_rate_limit_sets_retry_after(client, settings):
    settings.SANDBOX_RATE_LIMIT_RATE = 1.0

    response = post(client, settings)

    assert response.status_code == 429
    assert response["Retry-After"] == "10"


def test_slow_response_still_stores_the_message(client, settings):
    settings.SANDBOX_SLOW_RATE = 1.0

    assert post(client, settings).status_code == 202
    assert SandboxMessage.objects.count() == 1


def test_inbox_lists_messages(client, settings):
    post(client, settings)

    response = client.get(URL, headers={"Authorization": f"Bearer {settings.SANDBOX_API_KEY}"})

    assert [m["idempotency_key"] for m in response.json()["messages"]] == ["key-1"]


def make_message():
    return SandboxMessage.objects.create(
        idempotency_key="key-1", request_hash="x", to="a@example.com", subject="s", body="b"
    )


@respx.mock
def test_status_webhook_is_signed(settings):
    message = make_message()
    route = respx.post(settings.SANDBOX_WEBHOOK_URL).mock(return_value=httpx.Response(200))

    deliver_status_webhook(str(message.id))

    request = route.calls.last.request
    payload = json.loads(request.content)
    assert payload["type"] == "message.delivered"
    assert payload["idempotency_key"] == "key-1"
    header = request.headers["X-Sandbox-Signature"]
    timestamp = int(header.split(",")[0].removeprefix("t="))
    assert header == sign(settings.WEBHOOK_SECRET, timestamp, request.content)


@respx.mock
def test_status_webhook_failure_is_raised_for_retry(settings):
    message = make_message()
    respx.post(settings.SANDBOX_WEBHOOK_URL).mock(return_value=httpx.Response(500))

    with pytest.raises(httpx.HTTPStatusError):
        deliver_status_webhook(str(message.id))
