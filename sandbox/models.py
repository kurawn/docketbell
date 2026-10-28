from django.db import models

from core.models import BaseModel


class SandboxMessage(BaseModel):
    class Status(models.TextChoices):
        ACCEPTED = "accepted"
        DELIVERED = "delivered"
        FAILED = "failed"

    idempotency_key = models.CharField(max_length=100, unique=True)
    request_hash = models.CharField(max_length=64)
    to = models.CharField(max_length=254)
    subject = models.TextField()
    body = models.TextField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACCEPTED)
