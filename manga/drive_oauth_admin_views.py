"""Staff-only OAuth redirect/callback for Google Drive (no Ninja API)."""

from __future__ import annotations

import logging

from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest, HttpResponseRedirect
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from google_auth_oauthlib.flow import Flow

from manga.models import GoogleDriveApplicationCredentials

logger = logging.getLogger(__name__)


def _admin_change_url() -> str:
    return reverse("admin:manga_googledriveapplicationcredentials_change", args=(1,))


def _public_https_url(request: HttpRequest, location: str | None = None) -> str:
    """Google OAuth redirect_uri must be HTTPS; prod often sees HTTP behind TLS terminator."""
    url = request.build_absolute_uri(location)
    if url.startswith("http://"):
        return "https://" + url[len("http://") :]
    return url


def _redirect_uri(request: HttpRequest) -> str:
    return _public_https_url(request, reverse("admin_manga_gdrive_oauth_callback"))


def _superuser(u):
    return bool(u and u.is_active and u.is_superuser)


@user_passes_test(_superuser)
def google_drive_oauth_start(request: HttpRequest) -> HttpResponse:
    """Redirect browser to Google consent (offline access)."""
    row = GoogleDriveApplicationCredentials.objects.filter(pk=1).first()
    if not row:
        GoogleDriveApplicationCredentials.objects.create(pk=1)
        row = GoogleDriveApplicationCredentials.objects.get(pk=1)
    cid = (row.client_id or "").strip()
    csec = (row.client_secret or "").strip()
    if not cid or not csec:
        messages.error(
            request,
            "Set OAuth Web client id and client secret on Google Drive OAuth credentials first.",
        )
        return redirect(_admin_change_url())

    client_config = {
        "web": {
            "client_id": cid,
            "client_secret": csec,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": (row.token_uri or "").strip() or "https://oauth2.googleapis.com/token",
        },
    }
    flow = Flow.from_client_config(
        client_config,
        scopes=["https://www.googleapis.com/auth/drive.file"],
        redirect_uri=_redirect_uri(request),
    )
    auth_url, _state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    return HttpResponseRedirect(auth_url)


@csrf_exempt
@user_passes_test(_superuser)
def google_drive_oauth_callback(request: HttpRequest) -> HttpResponse:
    """Exchange code for refresh token; store on singleton row."""
    if request.GET.get("error"):
        messages.error(
            request,
            f"Google OAuth error: {request.GET.get('error_description') or request.GET.get('error')}",
        )
        return redirect(_admin_change_url())

    row = GoogleDriveApplicationCredentials.objects.filter(pk=1).first()
    if not row:
        return HttpResponseBadRequest("Save client id and secret on Google Drive OAuth credentials first.")

    cid = (row.client_id or "").strip()
    csec = (row.client_secret or "").strip()
    if not cid or not csec:
        return HttpResponseBadRequest("Client id/secret not configured.")

    client_config = {
        "web": {
            "client_id": cid,
            "client_secret": csec,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": (row.token_uri or "").strip() or "https://oauth2.googleapis.com/token",
        },
    }
    flow = Flow.from_client_config(
        client_config,
        scopes=["https://www.googleapis.com/auth/drive.file"],
        redirect_uri=_redirect_uri(request),
    )
    try:
        flow.fetch_token(authorization_response=_public_https_url(request))
    except Exception as exc:
        logger.exception("Google Drive OAuth token exchange failed")
        messages.error(request, f"OAuth token exchange failed: {exc}")
        return redirect(_admin_change_url())

    creds = flow.credentials
    row.refresh_token = creds.refresh_token or row.refresh_token
    row.access_token = creds.token or ""
    row.access_token_expires_at = creds.expiry
    row.save(
        update_fields=[
            "refresh_token",
            "access_token",
            "access_token_expires_at",
            "updated_at",
        ],
    )
    messages.success(request, "Google Drive OAuth connected. Uploads use this Google account's quota.")
    return redirect(_admin_change_url())
