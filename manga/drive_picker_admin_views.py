"""Staff JSON for Google Picker (Drive browse in admin; layout unchanged)."""

from __future__ import annotations

import logging

from django.contrib.auth.decorators import user_passes_test
from django.http import HttpRequest, HttpResponse, JsonResponse

from manga.google_drive_service import picker_access_token_payload

logger = logging.getLogger(__name__)


def _staff(u):
    return bool(u and u.is_active and u.is_staff)


@user_passes_test(_staff)
def google_drive_picker_token(request: HttpRequest) -> HttpResponse:
    """Return short-lived OAuth access token + browser API key for Google Picker JS."""
    if request.method != "GET":
        return JsonResponse({"error": "Method not allowed"}, status=405)
    try:
        payload = picker_access_token_payload()
    except RuntimeError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    except Exception:
        logger.exception("google_drive_picker_token failed")
        return JsonResponse({"error": "Failed to issue picker token."}, status=500)
    return JsonResponse(payload)
