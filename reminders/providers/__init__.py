from functools import cache

from django.conf import settings
from django.utils.module_loading import import_string

from reminders.providers.base import MessagingProvider


@cache
def get_provider() -> MessagingProvider:
    return import_string(settings.MESSAGING_PROVIDER)()
