from django.urls import path

from core.views import healthz
from sandbox.views import messages

urlpatterns = [
    path("healthz", healthz),
    path("sandbox/v1/messages", messages),
]
