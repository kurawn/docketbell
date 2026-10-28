from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class OutboundMessage:
    to: str
    subject: str
    body: str


@dataclass(frozen=True)
class SendResult:
    provider_message_id: str


@dataclass(frozen=True)
class DeliveryEvent:
    DELIVERED = "delivered"
    FAILED = "failed"

    event_id: str
    type: str
    idempotency_key: str
    provider_message_id: str
    reason: str = ""


class TransientProviderError(Exception):
    """Worth retrying: timeouts, outages, rate limits."""

    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class PermanentProviderError(Exception):
    """The provider rejected the request; retrying will not help."""


class InvalidWebhook(Exception):
    pass


class MessagingProvider(Protocol):
    def send(self, message: OutboundMessage, idempotency_key: str) -> SendResult: ...

    def parse_webhook(
        self, headers: Mapping[str, str], body: bytes, now: float | None = None
    ) -> DeliveryEvent: ...
