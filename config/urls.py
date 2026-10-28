from django.contrib import admin
from django.urls import include, path
from rest_framework.routers import SimpleRouter

from core.views import healthz
from matters.views import DeadlineViewSet, MatterViewSet
from reminders.webhooks import ProviderWebhookView

router = SimpleRouter()
router.register("matters", MatterViewSet, basename="matter")
router.register("deadlines", DeadlineViewSet, basename="deadline")

urlpatterns = [
    path("healthz", healthz),
    path("admin/", admin.site.urls),
    path("api/v1/webhooks/provider/", ProviderWebhookView.as_view()),
    path("api/v1/", include(router.urls)),
]

handler404 = "core.views.not_found"
handler500 = "core.views.server_error"
