"""Google Drive uploads (OAuth user credentials from Django admin)."""

from __future__ import annotations

import io
import json
import logging
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from django.conf import settings
from django.db import connection, transaction
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials as OAuthCredentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload, MediaIoBaseUpload

logger = logging.getLogger(__name__)

try:
    import fcntl
except ImportError:  # pragma: no cover — non-Unix
    fcntl = None  # type: ignore[misc, assignment]

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


def _drive_credentials() -> OAuthCredentials:
    oauth = _oauth_credentials()
    if oauth is None:
        raise RuntimeError(
            "Google Drive not configured: in Django admin open "
            "Manga → Google Drive OAuth credentials, set Web client id and secret, save, "
            "then use Start Google OAuth (superuser).",
        )
    return oauth


def _drive_service() -> Any:
    creds = _drive_credentials()
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _folder_resolve_uses_db_row_lock() -> bool:
    return connection.vendor in ("postgresql", "mysql", "oracle")


def _folder_resolve_lock_path() -> Path:
    raw = getattr(settings, "MANGA_GOOGLE_DRIVE_FOLDER_LOCK_PATH", None)
    if raw:
        return Path(str(raw).strip())
    return Path(settings.BASE_DIR) / "manga_google_drive_folder_resolve.lock"


@contextmanager
def _google_drive_folder_resolve_lock() -> Any:
    """Serialize find-or-create for Drive folders (parallel backup workers share parent)."""
    if _folder_resolve_uses_db_row_lock():
        from manga.models import GoogleDriveApplicationCredentials

        with transaction.atomic():
            GoogleDriveApplicationCredentials.objects.select_for_update().filter(pk=1).first()
            yield
        return
    if fcntl is None:
        logger.warning(
            "fcntl unavailable; Google Drive folder resolution may race if multiple workers run.",
        )
        yield
        return
    path = _folder_resolve_lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


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
    with _google_drive_folder_resolve_lock():
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


_DRIVE_QUOTA_HINT = (
    " Check the signed-in Google account’s Drive storage, or reconnect OAuth in admin "
    "(Manga → Google Drive OAuth credentials)."
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
                isinstance(msg, str) and "storage quota" in msg.lower()
            ):
                return base + _DRIVE_QUOTA_HINT
            return base
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass
        return f"Google Drive API HTTP {exc.resp.status if exc.resp else 'error'}"
    return str(exc) or exc.__class__.__name__
