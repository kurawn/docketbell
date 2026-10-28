"""Settings for docketbell; everything deploy-specific comes from the environment."""

import os
from pathlib import Path

from celery.schedules import crontab
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

DEV_DEFAULTS = {
    "SECRET_KEY": "dev-insecure-secret-key",
    "SANDBOX_API_KEY": "sandbox-dev-key",
    "WEBHOOK_SECRET": "whsec-dev",
}


def env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(name, default)


DEBUG = env("DEBUG", "1") == "1"
SECRET_KEY = env("SECRET_KEY", DEV_DEFAULTS["SECRET_KEY"])
SANDBOX_API_KEY = env("SANDBOX_API_KEY", DEV_DEFAULTS["SANDBOX_API_KEY"])
WEBHOOK_SECRET = env("WEBHOOK_SECRET", DEV_DEFAULTS["WEBHOOK_SECRET"])

if not DEBUG:
    for _name, _value in (
        ("SECRET_KEY", SECRET_KEY),
        ("SANDBOX_API_KEY", SANDBOX_API_KEY),
        ("WEBHOOK_SECRET", WEBHOOK_SECRET),
    ):
        if _value == DEV_DEFAULTS[_name]:
            raise ImproperlyConfigured(f"{_name} must be set to a real secret when DEBUG is off")

ALLOWED_HOSTS = env("ALLOWED_HOSTS", "*").split(",")

INSTALLED_APPS = [
    "unfold",  # admin theme; must come before django.contrib.admin
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework.authtoken",
    "core",
    "workdays",
    "matters",
    "reminders",
    "sandbox",
]

# Sessions, CSRF and messages are for the admin; the API itself stays token-only.
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    }
]

STATIC_URL = "static/"
STATIC_ROOT = env("STATIC_ROOT", str(BASE_DIR / "staticfiles"))
WHITENOISE_USE_FINDERS = DEBUG  # serve straight from the apps in dev, no collectstatic needed

UNFOLD = {"SITE_TITLE": "docketbell admin", "SITE_HEADER": "docketbell", "SITE_SYMBOL": "notifications"}

ROOT_URLCONF = env("ROOT_URLCONF", "config.urls")
WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("POSTGRES_DB", "docketbell"),
        "USER": env("POSTGRES_USER", "docketbell"),
        "PASSWORD": env("POSTGRES_PASSWORD", "docketbell"),
        "HOST": env("POSTGRES_HOST", "db"),
        "PORT": env("POSTGRES_PORT", "5432"),
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LANGUAGE_CODE = "en-gb"
TIME_ZONE = "Europe/London"
USE_I18N = False
USE_TZ = True

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.TokenAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PAGINATION_CLASS": "core.pagination.CreatedCursorPagination",
    "PAGE_SIZE": 50,
    "EXCEPTION_HANDLER": "core.exceptions.error_handler",
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
}

# Celery
CELERY_BROKER_URL = env("REDIS_URL", "redis://redis:6379/0")
CELERY_TASK_DEFAULT_QUEUE = "default"
CELERY_TASK_ROUTES = {"sandbox.*": {"queue": "sandbox"}}
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TASK_IGNORE_RESULT = True
CELERY_TIMEZONE = TIME_ZONE
CELERY_BEAT_SCHEDULE = {
    "dispatch-due-reminders": {"task": "reminders.dispatch_due_reminders", "schedule": 30.0},
    "refresh-bank-holidays": {
        "task": "workdays.refresh_bank_holidays",
        "schedule": crontab(hour=3, minute=0),
    },
}

# Reminders
MESSAGING_PROVIDER = env("MESSAGING_PROVIDER", "reminders.providers.sandbox.SandboxProvider")
REMINDER_SEND_HOUR = 9
ESCALATION_SEND_HOUR = 15
DISPATCH_BATCH_SIZE = 100
SEND_LEASE_SECONDS = 120
MAX_SEND_ATTEMPTS = 5

# Bank holidays
BANK_HOLIDAY_REGION = env("BANK_HOLIDAY_REGION", "england-and-wales")
BANK_HOLIDAYS_URL = "https://www.gov.uk/bank-holidays.json"

# Sandbox messaging provider
SANDBOX_BASE_URL = env("SANDBOX_BASE_URL", "http://provider:8001")
SANDBOX_WEBHOOK_URL = env("SANDBOX_WEBHOOK_URL", "http://api:8000/api/v1/webhooks/provider/")
SANDBOX_FAIL_RATE = float(env("SANDBOX_FAIL_RATE", "0.10"))
SANDBOX_RATE_LIMIT_RATE = float(env("SANDBOX_RATE_LIMIT_RATE", "0.05"))
SANDBOX_SLOW_RATE = float(env("SANDBOX_SLOW_RATE", "0.10"))
SANDBOX_SLOW_SECONDS = float(env("SANDBOX_SLOW_SECONDS", "8"))
SANDBOX_DELIVERY_FAIL_RATE = float(env("SANDBOX_DELIVERY_FAIL_RATE", "0.10"))
