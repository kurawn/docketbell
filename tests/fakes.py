import httpx
from django.test import Client

from reminders.providers.base import SendResult


class FakeProvider:
    """Plays back outcomes in order: an exception is raised, a string is a message id."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def send(self, message, idempotency_key):
        self.calls.append((message, idempotency_key))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return SendResult(provider_message_id=outcome)


class DjangoClientTransport(httpx.BaseTransport):
    """Routes httpx calls into the Django test client; can fake a timeout after the server handled it."""

    def __init__(self, timeout_first: int = 0):
        self.client = Client()
        self.timeouts_left = timeout_first

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        skip = ("host", "content-length", "content-type")
        headers = {k: v for k, v in request.headers.items() if k.lower() not in skip}
        response = self.client.generic(
            request.method,
            request.url.path,
            data=request.read(),
            content_type=request.headers.get("content-type", ""),
            headers=headers,
        )
        if self.timeouts_left:
            self.timeouts_left -= 1
            raise httpx.ReadTimeout("simulated read timeout", request=request)
        return httpx.Response(response.status_code, headers=dict(response.headers), content=response.content)
