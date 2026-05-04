"""Google Drive uploads: OAuth user (preferred) or service account."""

from __future__ import annotations

import io
import json
import logging
import os
from typing import Any

from django.conf import settings
from google.auth.transport.requests import Request
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials as OAuthCredentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload, MediaIoBaseUpload

logger = logging.getLogger(__name__)

_DRIVE_SCOPES = ("https://www.googleapis.com/auth/drive.file",)
_DRIVE_MIME_FOLDER = "application/vnd.google-apps.folder"


def _persist_oauth_tokens(creds: OAuthCredentials) -> None:
    from manga.models import GoogleDriveApplicationCredentials

    row = GoogleDriveApplicationCredentials.objects.filter(pk=1).first()
    if not row:
        return
    row.access_token = creds.token or ""
    row.access_token_expires_at = creds.expiry
    if creds.refresh_token:
        row.refresh_token = creds.refresh_token
    row.save(
        update_fields=[
            "access_token",
            "access_token_expires_at",
            "refresh_token",
            "updated_at",
        ],
    )


def _oauth_credentials() -> OAuthCredentials | None:
    from manga.models import GoogleDriveApplicationCredentials

    row = GoogleDriveApplicationCredentials.get_solo()
    if not row:
        return None
    refresh = (row.refresh_token or "").strip()
    cid = (row.client_id or "").strip()
    csec = (row.client_secret or "").strip()
    if not refresh or not cid or not csec:
        return None
    token_uri = (row.token_uri or "").strip() or "https://oauth2.googleapis.com/token"
    creds = OAuthCredentials(
        token=(row.access_token or "").strip() or None,
        refresh_token=refresh,
        token_uri=token_uri,
        client_id=cid,
        client_secret=csec,
        scopes=list(_DRIVE_SCOPES),
    )
    if creds.expired or not creds.token:
        creds.refresh(Request())
        _persist_oauth_tokens(creds)
    return creds


def _service_account_credentials() -> service_account.Credentials:
    path = getattr(settings, "GOOGLE_DRIVE_SERVICE_ACCOUNT_FILE", "") or ""
    raw_json = getattr(settings, "GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON", "") or ""
    if path:
        p = os.path.expanduser(path)
        if not os.path.isfile(p):
            msg = f"GOOGLE_DRIVE_SERVICE_ACCOUNT_FILE not found: {p}"
            raise RuntimeError(msg)
        return service_account.Credentials.from_service_account_file(p, scopes=_DRIVE_SCOPES)
    if raw_json.strip():
        try:
            info = json.loads(raw_json)
        except json.JSONDecodeError as exc:
            raise RuntimeError("GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON is not valid JSON") from exc
        return service_account.Credentials.from_service_account_info(info, scopes=_DRIVE_SCOPES)
    raise RuntimeError(
        "Google Drive not configured: complete OAuth in admin (Google Drive OAuth credentials) "
        "or set GOOGLE_DRIVE_SERVICE_ACCOUNT_FILE / GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON",
    )


def _drive_credentials() -> OAuthCredentials | service_account.Credentials:
    oauth = _oauth_credentials()
    if oauth is not None:
        return oauth
    return _service_account_credentials()


def _drive_service() -> Any:
    creds = _drive_credentials()
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _escape_drive_query_literal(value: str) -> str:
    """Escape a string for use inside single-quoted literals in Drive API ``q``."""
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _find_folder_id(*, service: Any, parent_id: str, name: str) -> str | None:
    safe_name = _escape_drive_query_literal(name)
    q = (
        f"name = '{safe_name}' and mimeType = '{_DRIVE_MIME_FOLDER}' "
        f"and '{parent_id}' in parents and trashed = false"
    )
    resp = (
        service.files()
        .list(
            q=q,
            spaces="drive",
            fields="files(id, name)",
            pageSize=10,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        )
        .execute()
    )
    files = resp.get("files") or []
    if not files:
        return None
    return str(files[0]["id"])


def _create_folder(*, service: Any, parent_id: str, name: str) -> str:
    body = {
        "name": name,
        "mimeType": _DRIVE_MIME_FOLDER,
        "parents": [parent_id],
    }
    created = (
        service.files()
        .create(
            body=body,
            fields="id",
            supportsAllDrives=True,
        )
        .execute()
    )
    return str(created["id"])


def _ensure_folder(*, service: Any, parent_id: str, name: str) -> str:
    found = _find_folder_id(service=service, parent_id=parent_id, name=name)
    if found:
        return found
    return _create_folder(service=service, parent_id=parent_id, name=name)


def _root_folder_name() -> str:
    n = (getattr(settings, "MANGA_GOOGLE_DRIVE_ROOT_FOLDER_NAME", None) or "Manga").strip()
    return n or "Manga"


def _drive_parent_for_root_folder() -> str:
    """Folder id where root ``Manga`` folder is created; ``root`` = authenticated user's My Drive."""
    pid = (getattr(settings, "MANGA_GOOGLE_DRIVE_PARENT_FOLDER_ID", None) or "").strip()
    return pid or "root"


def ensure_series_drive_folder(*, series_name: str) -> str:
    """Return Drive folder id for ``<root>/<series_name>/`` (creates ``Manga`` + series folder only)."""
    service = _drive_service()
    manga_id = _ensure_folder(
        service=service,
        parent_id=_drive_parent_for_root_folder(),
        name=_root_folder_name(),
    )
    return _ensure_folder(service=service, parent_id=manga_id, name=series_name)


def find_existing_file_id_with_same_size(
    *,
    parent_folder_id: str,
    drive_filename: str,
    expected_size: int,
) -> str | None:
    """Return Drive file id if a non-trashed file with *drive_filename* exists under *parent_folder_id* with that size."""
    service = _drive_service()
    safe_name = _escape_drive_query_literal(drive_filename)
    q = (
        f"name = '{safe_name}' and mimeType != '{_DRIVE_MIME_FOLDER}' "
        f"and '{parent_folder_id}' in parents and trashed = false"
    )
    resp = (
        service.files()
        .list(
            q=q,
            spaces="drive",
            fields="files(id, size)",
            pageSize=25,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        )
        .execute()
    )
    want = str(int(expected_size))
    for f in resp.get("files") or []:
        if str(f.get("size") or "") == want:
            return str(f["id"])
    return None


def upload_file_to_folder(
    *,
    local_path: str,
    drive_filename: str,
    parent_folder_id: str,
) -> str:
    """Upload *local_path* into *parent_folder_id*; returns Drive file id."""
    service = _drive_service()
    media = MediaFileUpload(
        local_path,
        mimetype="application/vnd.comicbook+zip",
        resumable=True,
    )
    body = {"name": drive_filename, "parents": [parent_folder_id]}
    request = service.files().create(
        body=body,
        media_body=media,
        fields="id",
        supportsAllDrives=True,
    )
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status is not None:
            logger.debug("Drive upload %s %d%%", drive_filename, int(status.progress() * 100))
    if not response or "id" not in response:
        raise RuntimeError("Drive upload finished without file id")
    return str(response["id"])


def upload_bytes_to_folder(
    *,
    content: bytes,
    drive_filename: str,
    parent_folder_id: str,
    mime_type: str = "application/octet-stream",
) -> str:
    """Small uploads (tests) via in-memory body."""
    service = _drive_service()
    stream = io.BytesIO(content)
    media = MediaIoBaseUpload(stream, mimetype=mime_type, resumable=False)
    body = {"name": drive_filename, "parents": [parent_folder_id]}
    created = (
        service.files()
        .create(
            body=body,
            media_body=media,
            fields="id",
            supportsAllDrives=True,
        )
        .execute()
    )
    return str(created["id"])


_SA_NO_QUOTA_HINT = (
    " Google changed policy (Apr 2025): new service accounts cannot use storage in a "
    "personal My Drive folder, even if shared with the SA. Use a Shared drive folder as "
    "MANGA_GOOGLE_DRIVE_PARENT_FOLDER_ID (add SA as Content manager), or an older SA, or "
    "complete Google Drive OAuth in Django admin (uses your Google account quota)."
)


def drive_http_error_message(exc: BaseException) -> str:
    if isinstance(exc, HttpError):
        try:
            payload = json.loads(exc.content.decode()) if exc.content else {}
            err = payload.get("error", {})
            msg = err.get("message") if isinstance(err, dict) else None
            reasons = err.get("errors") if isinstance(err, dict) else None
            reason_codes: list[str] = []
            if isinstance(reasons, list):
                for item in reasons:
                    if isinstance(item, dict) and item.get("reason"):
                        reason_codes.append(str(item["reason"]))
            base: str | None = None
            if msg:
                base = f"Google Drive API error: {msg}"
            if base is None:
                base = f"Google Drive API HTTP {exc.resp.status if exc.resp else 'error'}"
            if "storageQuotaExceeded" in reason_codes or (
                isinstance(msg, str) and "Service Accounts do not have storage quota" in msg
            ):
                return base + _SA_NO_QUOTA_HINT
            return base
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass
        return f"Google Drive API HTTP {exc.resp.status if exc.resp else 'error'}"
    return str(exc) or exc.__class__.__name__
