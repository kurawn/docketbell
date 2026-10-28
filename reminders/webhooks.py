import json
import logging

from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from reminders.delivery import apply_delivery_event
from reminders.providers import get_provider
from reminders.providers.base import InvalidWebhook

logger = logging.getLogger(__name__)


class ProviderWebhookView(APIView):
    authentication_classes = []  # authenticated by the provider's signature instead
    permission_classes = [AllowAny]

    def post(self, request):
        body = request.body
        try:
            event = get_provider().parse_webhook(request.headers, body)
        except InvalidWebhook as exc:
            logger.warning("Rejected provider webhook: %s", exc)
            error = {"code": "invalid_signature", "message": str(exc), "details": {}}
            return Response({"error": error}, status=401)
        return Response({"status": apply_delivery_event(event, json.loads(body))})
