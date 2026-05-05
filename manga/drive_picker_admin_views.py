"""Superuser-only Google Picker in Django admin (Option A: server-minted OAuth access token)."""

from __future__ import annotations

import logging

from django.contrib.auth.decorators import user_passes_test
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods, require_POST

from manga.google_drive_service import get_drive_access_token_for_picker
from manga.models import GoogleDriveApplicationCredentials

logger = logging.getLogger(__name__)


def _superuser(u):
    return bool(u and u.is_active and u.is_superuser)


@user_passes_test(_superuser)
@ensure_csrf_cookie
@require_http_methods(["GET"])
def google_drive_picker(request):
    row = GoogleDriveApplicationCredentials.get_solo()
    api_key = (row.browser_api_key or "").strip() if row else ""
    client_id = (row.client_id or "").strip() if row else ""
    has_refresh = bool(row and (row.refresh_token or "").strip())
    ready = bool(has_refresh and api_key and client_id)
    return render(
        request,
        "manga/admin/google_drive_picker.html",
        {
            "picker_api_key_configured": bool(api_key),
            "picker_client_id_configured": bool(client_id),
            "picker_ready": ready,
            "has_refresh": has_refresh,
            "browser_api_key": api_key,
        },
    )


@user_passes_test(_superuser)
@require_POST
def google_drive_picker_access_token(request):
    try:
        token = get_drive_access_token_for_picker()
    except RuntimeError as exc:
        logger.warning("Drive picker token: %s", exc)
        return JsonResponse({"error": str(exc)}, status=503)
    return JsonResponse({"access_token": token})
