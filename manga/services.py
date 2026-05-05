import base64
import logging
import os
import posixpath
import time
from datetime import UTC, datetime, timedelta
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any, BinaryIO, Literal

from django.conf import settings
from django.db import connection, transaction
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone
from django_q.tasks import async_task
from PIL import Image
from rapidfuzz import fuzz

from manga.cbztools.manga_v2 import process_manga
from manga.cbztools.manhwa_v3 import process_manhwa_v3
from manga.cbztools.utils import (
    alphanum_key,
    delete_dropbox_path,
    dropbox_download_name_for_series_cbz,
    dropbox_remote_path_for_series_cbz,
    get_dropbox_space_bytes,
    is_image,
    list_dropbox_files,
    upload_to_dropbox,
)
from manga.mangabaka_client import MangaBakaAPIError, fetch_series_detail, search_series
from manga.google_drive_service import (
    drive_http_error_message,
    download_drive_file_to_path,
    ensure_series_drive_folder,
    find_existing_file_id_with_same_size,
    get_manga_root_drive_folder_id_optional,
    get_series_drive_folder_id_optional,
    list_child_folder_names_and_ids,
    list_drive_cbz_files_in_folder,
    list_drive_file_names_in_folder,
    upload_file_to_folder,
)
from manga.models import (
    CbzConvertJob,
    CbzConvertJobStatus,
    CbzConvertKind,
    GoogleDriveBackupJob,
    GoogleDriveBackupJobStatus,
    GoogleDriveRestoreJob,
    GoogleDriveRestoreJobStatus,
    Series,
    SeriesInfo,
    SeriesItem,
    normalize_manga_hidden_rel_path,
)

logger = logging.getLogger(__name__)

# Serialize Dropbox eviction + upload across workers (PostgreSQL only).
_DROPBOX_UPLOAD_ADVISORY_LOCK_1 = 0x6D616E67
_DROPBOX_UPLOAD_ADVISORY_LOCK_2 = 0x64726F70


def _filesystem_created_at_from_stat(st: os.stat_result) -> datetime | None:
    """UTC timestamp from ``st_birthtime`` when present, else ``st_ctime`` (platform-dependent)."""
    birth = getattr(st, "st_birthtime", None)
    ts = float(birth) if birth is not None else float(st.st_ctime)
    try:
        return datetime.fromtimestamp(ts, tz=UTC)
    except (OSError, OverflowError, ValueError):
        return None


@dataclass(frozen=True)
class MangaListItem:
    name: str
    path: str
    is_dir: bool
    size: int | None
    is_converted: bool
    file_created_at: datetime | None = None


@dataclass(frozen=True)
class CbzDownload:
    """Resolved on-disk CBZ for streaming to client."""

    absolute_path: str
    filename: str


@dataclass(frozen=True)
class CbzPagesDownload:
    """Subset CBZ built from a slice of sorted image members."""

    content: BinaryIO
    filename: str


def list_series(
    *,
    manga_root: str,
    limit: int = 100,
    offset: int = 0,
    category: str | None = None,
    search: str | None = None,
) -> list[Series]:
    """Query ``Series`` for ``manga_root`` (normalized), ordered by display ``name``.

    *category* ``None``: no category filter. Non-empty *category*: filter rows whose
    stored category equals that string. Empty or whitespace-only *category* raises
    ``ValueError``.

    *search* ``None``: no text filter. Non-empty *search*: case-insensitive substring
    match on ``name``, ``series_rel_path``, or ``category``. Empty or whitespace-only
    *search* raises ``ValueError``.
    """
    root_norm = os.path.abspath(os.path.expanduser(manga_root))
    qs = Series.objects.filter(library_root=root_norm).order_by("name", "series_rel_path")
    if category is not None:
        cat = category.strip()
        if not cat:
            raise ValueError("category filter must be a non-empty string when set")
        qs = qs.filter(category=cat)
    if search is not None:
        q = search.strip()
        if not q:
            raise ValueError("search must be a non-empty string when set")
        qs = qs.filter(
            Q(name__icontains=q)
            | Q(series_rel_path__icontains=q)
            | Q(category__icontains=q),
        )
    return list(qs.select_related("series_info")[offset : offset + limit])


def list_distinct_series_categories(*, manga_root: str) -> list[str]:
    """Non-empty distinct ``Series.category`` values for *manga_root*, sorted ascending."""
    root_norm = os.path.abspath(os.path.expanduser(manga_root))
    return list(
        Series.objects.filter(library_root=root_norm)
        .exclude(category="")
        .values_list("category", flat=True)
        .distinct()
        .order_by("category")
    )


def list_series_items(
    *,
    manga_root: str,
    series_id: int,
    limit: int = 100,
    offset: int = 0,
    is_converted: bool | None = None,
) -> list[SeriesItem]:
    """Query ``SeriesItem`` for ``series_id`` under ``manga_root`` (natural order by ``filename``)."""
    root_norm = os.path.abspath(os.path.expanduser(manga_root))
    try:
        series = Series.objects.get(pk=series_id, library_root=root_norm)
    except Series.DoesNotExist as exc:
        raise ValueError("Series not found") from exc
    qs = series.items.all()
    if is_converted is not None:
        qs = qs.filter(is_converted=is_converted)
    rows = list(qs)
    rows.sort(key=lambda r: alphanum_key(r.filename))
    return rows[offset : offset + limit]


def get_series(*, manga_root: str, series_id: int) -> Series:
    """Load single ``Series`` for ``series_id`` under ``manga_root`` (normalized)."""
    root_norm = os.path.abspath(os.path.expanduser(manga_root))
    try:
        return Series.objects.select_related("series_info").get(
            pk=series_id,
            library_root=root_norm,
        )
    except Series.DoesNotExist as exc:
        raise ValueError("Series not found") from exc


def _path_under_manga_root(*, manga_root: str, rel_path: str) -> str:
    root_abs = os.path.abspath(os.path.expanduser(manga_root))
    joined = os.path.abspath(os.path.join(root_abs, rel_path))
    try:
        common = os.path.commonpath([root_abs, joined])
    except ValueError:
        raise ValueError("Invalid path") from None
    if common != root_abs:
        raise ValueError("Path outside manga root")
    return joined


def _chapter_replacement_for_hash_stem(stem: str) -> str:
    """Replace leading ``#`` with ``Chapter``; insert one space after ``Chapter`` if next char is not
    already whitespace (so ``#12`` → ``Chapter 12``; ``# 12`` → ``Chapter 12``). *stem* must be
    non-empty and start with ``#``."""
    rest = stem[1:]
    if not rest:
        return "Chapter"
    if rest[0].isspace():
        return "Chapter" + rest
    return f"Chapter {rest}"


def clean_cbz_display_name(filename: str) -> str | None:
    """Derive cleaned ``.cbz`` basename.

    Underscore rules first: 2+ underscores → segment between first two; exactly 1 → segment before
    first underscore. If there are no underscores, only the ``#`` rule applies: leading ``#`` becomes
    ``Chapter`` (with a space before the rest of the title when needed). After underscore
    extraction, the same ``#`` → ``Chapter`` rule applies to the result stem. Returns ``None`` if
    nothing changes or result invalid."""
    if not filename.lower().endswith(".cbz"):
        return None
    stem = filename[:-4]
    n = stem.count("_")
    if n == 0:
        if not stem.startswith("#"):
            return None
        new_stem = _chapter_replacement_for_hash_stem(stem)
    elif n >= 2:
        _a, middle, _rest = stem.split("_", 2)
        new_stem = middle
    else:
        new_stem = stem.split("_", 1)[0]
    new_stem = new_stem.strip()
    if not new_stem:
        return None
    if new_stem.startswith("#"):
        new_stem = _chapter_replacement_for_hash_stem(new_stem)
    out = f"{new_stem}.cbz"
    return out if out != filename else None


def clean_series_item_filename_on_disk(*, item_id: int) -> SeriesItem:
    """Rename CBZ on disk and update ``SeriesItem`` ``rel_path`` / ``filename``.

    Uses ``clean_cbz_display_name`` (underscore rules, then ``#`` → ``Chapter`` with spacing); no-op
    if name already clean. Raises if target basename exists.
    """
    try:
        item = SeriesItem.objects.select_related("series").get(pk=item_id)
    except SeriesItem.DoesNotExist as exc:
        raise ValueError("Item not found") from exc

    manga_root = item.series.library_root
    old_base = os.path.basename(item.rel_path)
    new_base = clean_cbz_display_name(old_base)
    if new_base is None or new_base == old_base:
        return item

    parent_rel = posixpath.dirname(item.rel_path)
    new_rel = posixpath.join(parent_rel, new_base) if parent_rel else new_base

    old_abs = _path_under_manga_root(manga_root=manga_root, rel_path=item.rel_path)
    new_abs = _path_under_manga_root(manga_root=manga_root, rel_path=new_rel)

    if not os.path.isfile(old_abs):
        raise ValueError("CBZ not found")
    if os.path.exists(new_abs):
        raise ValueError("Target filename already exists")

    with transaction.atomic():
        os.rename(old_abs, new_abs)
        try:
            item.rel_path = new_rel.replace("\\", "/")
            item.filename = new_base
            item.save(update_fields=["rel_path", "filename"])
        except Exception:
            try:
                os.rename(new_abs, old_abs)
            except OSError:
                logger.exception(
                    "clean_series_item_filename_on_disk: rollback rename failed (item_id=%s)",
                    item_id,
                )
            raise

    return SeriesItem.objects.get(pk=item.pk)


def _series_item_for_manga_root(*, manga_root: str, item_id: int) -> SeriesItem:
    root_norm = os.path.abspath(os.path.expanduser(manga_root))
    try:
        item = SeriesItem.objects.select_related("series").get(pk=item_id)
    except SeriesItem.DoesNotExist:
        raise ValueError("Item not found") from None
    if item.series.library_root != root_norm:
        raise ValueError("Item not found") from None
    return item


def _dropbox_upload_bytes_needed_for_file(abs_path: str) -> int:
    try:
        sz = os.path.getsize(abs_path)
    except OSError:
        return 0
    return max(int(sz), 1)


def _dropbox_advisory_lock_xact() -> None:
    """Serialize Dropbox eviction + upload when DB is PostgreSQL (django-q workers)."""
    if connection.vendor != "postgresql":
        return
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(%s, %s)",
            [_DROPBOX_UPLOAD_ADVISORY_LOCK_1, _DROPBOX_UPLOAD_ADVISORY_LOCK_2],
        )


def _evict_series_item_from_dropbox(*, item: SeriesItem) -> None:
    remote = dropbox_remote_path_for_series_cbz(
        item.rel_path,
        dropbox_download_name_for_series_cbz(item.rel_path, item.filename),
    )
    delete_dropbox_path(remote)
    SeriesItem.objects.filter(pk=item.pk).update(
        is_converted=False,
        dropbox_uploaded_at=None,
    )


def _ensure_dropbox_space_for_upload(
    *,
    manga_root: str,
    reserve_item_id: int,
    upload_bytes: int,
) -> None:
    """Delete oldest-in-Dropbox CBZs until quota allows upload + 250% headroom (free >= 3.5× upload size)."""
    while True:
        used, allocated = get_dropbox_space_bytes()
        if allocated is None:
            break
        need_remove = max(0, used - allocated + int(3.5 * upload_bytes))
        if need_remove <= 0:
            break
        victim = (
            SeriesItem.objects.filter(
                is_converted=True,
                dropbox_uploaded_at__isnull=False,
                series__library_root=os.path.abspath(os.path.expanduser(manga_root)),
            )
            .exclude(pk=reserve_item_id)
            .order_by("dropbox_uploaded_at", "pk")
            .first()
        )
        if victim is None:
            raise RuntimeError(
                "Dropbox storage full: no eligible cached rows left to evict "
                f"(need ~{need_remove} bytes freed; upload ~{upload_bytes} bytes).",
            )
        logger.info(
            "Evicting Dropbox copy for SeriesItem id=%s rel_path=%s to free space",
            victim.pk,
            victim.rel_path,
        )
        _evict_series_item_from_dropbox(item=victim)


def resolve_cbz_download(*, manga_root: str, item_id: int) -> CbzDownload:
    """Resolve cached ``SeriesItem`` to a readable ``.cbz`` under ``manga_root``."""
    item = _series_item_for_manga_root(manga_root=manga_root, item_id=item_id)
    path = item.rel_path
    filename = os.path.basename(path)
    if not filename.lower().endswith(".cbz"):
        raise ValueError("Not a CBZ file")
    abs_path = _path_under_manga_root(manga_root=manga_root, rel_path=path)
    if not os.path.isfile(abs_path):
        raise ValueError("CBZ not found")
    return CbzDownload(absolute_path=abs_path, filename=filename)


def _sorted_image_names_in_cbz(abs_cbz_path: str) -> list[str]:
    """Archive member paths that look like images, ordered like ``sort_nicely`` (alphanum)."""
    try:
        with zipfile.ZipFile(abs_cbz_path, "r") as zf:
            names = [
                n
                for n in zf.namelist()
                if not n.endswith("/") and is_image(os.path.basename(n.replace("\\", "/")))
            ]
    except zipfile.BadZipFile as exc:
        raise ValueError("Invalid CBZ file") from exc
    names.sort(key=lambda n: alphanum_key(n.replace("\\", "/")))
    return names


# Stored series cover: fixed width, portrait 11:17; vertical overflow crops from bottom (top-aligned).
COVER_THUMB_WIDTH = 128
COVER_THUMB_ASPECT_W = 11
COVER_THUMB_ASPECT_H = 17


def _cover_thumb_jpeg_base64_from_image_bytes(raw: bytes) -> str | None:
    """Crop to 11:17 (top-aligned when source taller), resize width to ``COVER_THUMB_WIDTH``, JPEG base64."""
    try:
        im = Image.open(BytesIO(raw))
        im.load()
    except OSError:
        return None
    rgb = im.convert("RGB")
    w, h = rgb.size
    if w < 1 or h < 1:
        return None
    tw, th = COVER_THUMB_ASPECT_W, COVER_THUMB_ASPECT_H
    src_ratio = w / h
    tgt_ratio = tw / th
    if src_ratio > tgt_ratio:
        crop_w = int(round(h * tw / th))
        crop_w = min(crop_w, w)
        left = (w - crop_w) // 2
        box = (left, 0, left + crop_w, h)
    else:
        crop_h = int(round(w * th / tw))
        crop_h = min(crop_h, h)
        box = (0, 0, w, crop_h)
    cropped = rgb.crop(box)
    out_h = max(1, int(round(COVER_THUMB_WIDTH * th / tw)))
    thumb = cropped.resize((COVER_THUMB_WIDTH, out_h), Image.Resampling.LANCZOS)
    buf = BytesIO()
    thumb.save(buf, format="JPEG", quality=85)
    return base64.standard_b64encode(buf.getvalue()).decode("ascii")


def first_cbz_page_as_base64(abs_cbz_path: str) -> tuple[str | None, str | None]:
    """First archive member with image-like name that PIL decodes (natural sort).

    Skips extension-only matches and corrupt/truncated bytes so cover is always
    a normalized JPEG thumb (128w, 11:17, top crop if tall), or ``(None, None)``.
    """
    try:
        names = _sorted_image_names_in_cbz(abs_cbz_path)
    except ValueError:
        return None, None
    if not names:
        return None, None
    try:
        zf = zipfile.ZipFile(abs_cbz_path, "r")
    except (zipfile.BadZipFile, OSError):
        return None, None
    try:
        for name in names:
            try:
                data = zf.read(name)
            except KeyError:
                continue
            if not data:
                continue
            thumb_b64 = _cover_thumb_jpeg_base64_from_image_bytes(data)
            if thumb_b64 is not None:
                return thumb_b64, "image/jpeg"
    finally:
        zf.close()
    return None, None


def _refresh_series_item_cover_if_missing(*, manga_root: str, item: SeriesItem) -> None:
    """Set ``cover_image_*`` from first archive image of this CBZ when still unset."""
    if (item.cover_image_base64 or "").strip():
        return
    abs_cbz = _path_under_manga_root(manga_root=manga_root, rel_path=item.rel_path)
    if not os.path.isfile(abs_cbz):
        return
    b64, mime = first_cbz_page_as_base64(abs_cbz)
    item.cover_image_base64 = b64
    item.cover_image_mime_type = mime or ""
    item.save(update_fields=["cover_image_base64", "cover_image_mime_type"])


def _refresh_series_cover_from_first_cbz(*, manga_root: str, series: Series) -> None:
    """Set ``cover_image_*`` from first page of lexically first ``.cbz`` in series."""
    rows = list(series.items.all())
    if not rows:
        series.cover_image_base64 = None
        series.cover_image_mime_type = ""
        series.save(update_fields=["cover_image_base64", "cover_image_mime_type"])
        return
    first_item = min(rows, key=lambda r: alphanum_key(r.filename))
    abs_cbz = _path_under_manga_root(manga_root=manga_root, rel_path=first_item.rel_path)
    if not os.path.isfile(abs_cbz):
        series.cover_image_base64 = None
        series.cover_image_mime_type = ""
        series.save(update_fields=["cover_image_base64", "cover_image_mime_type"])
        return
    b64, mime = first_cbz_page_as_base64(abs_cbz)
    series.cover_image_base64 = b64
    series.cover_image_mime_type = mime or ""
    series.save(update_fields=["cover_image_base64", "cover_image_mime_type"])


def build_cbz_page_slice(
    *,
    manga_root: str,
    item_id: int,
    offset: int,
    limit: int,
) -> CbzPagesDownload:
    """Build a CBZ containing ``limit`` image members starting at ``offset`` (sorted order)."""
    resolved = resolve_cbz_download(manga_root=manga_root, item_id=item_id)
    members = _sorted_image_names_in_cbz(resolved.absolute_path)
    if not members:
        raise ValueError("No image pages in CBZ")
    if offset >= len(members):
        raise ValueError("Offset out of range")
    slice_names = members[offset : offset + limit]
    if not slice_names:
        raise ValueError("Offset out of range")

    stem, ext = os.path.splitext(resolved.filename)
    if ext.lower() != ".cbz":
        ext = ".cbz"
    last_idx = offset + len(slice_names) - 1
    out_filename = f"{stem}_m{offset}-{last_idx}{ext}"

    out = tempfile.SpooledTemporaryFile(max_size=16 * 1024 * 1024, mode="w+b")
    try:
        with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zout:
            with zipfile.ZipFile(resolved.absolute_path, "r") as zin:
                for name in slice_names:
                    info = zin.getinfo(name)
                    zout.writestr(info, zin.read(name))
    except Exception:
        out.close()
        raise

    out.seek(0)
    return CbzPagesDownload(content=out, filename=out_filename)


def _dropbox_list_segment_for_folder(*, parent_rel: str) -> str:
    """Last path segment for Dropbox folder listing (matches ``list_dropbox_files`` query)."""
    if not parent_rel:
        return os.path.split("")[1]
    return os.path.split(parent_rel.replace("/", os.sep))[-1]


def _refresh_series_items_google_drive_backed_up(*, series: Series) -> None:
    """Reconcile ``SeriesItem.is_backed_up`` with Drive folder listing (no folder creation)."""
    try:
        folder_id = get_series_drive_folder_id_optional(series_name=series.name)
    except Exception:
        logger.warning(
            "Google Drive backup flag refresh skipped (series id=%s)",
            series.pk,
            exc_info=True,
        )
        return
    if not folder_id:
        if series.items.filter(is_backed_up=True).exists():
            series.items.filter(is_backed_up=True).update(is_backed_up=False)
        return
    try:
        names = list_drive_file_names_in_folder(parent_folder_id=folder_id)
    except Exception:
        logger.warning(
            "Google Drive backup flag refresh failed listing folder (series id=%s)",
            series.pk,
            exc_info=True,
        )
        return
    want_true: list[int] = []
    want_false: list[int] = []
    for item in series.items.all().only("pk", "filename", "is_backed_up"):
        want = item.filename in names
        if want and not item.is_backed_up:
            want_true.append(item.pk)
        elif not want and item.is_backed_up:
            want_false.append(item.pk)
    if want_true:
        SeriesItem.objects.filter(pk__in=want_true).update(is_backed_up=True)
    if want_false:
        SeriesItem.objects.filter(pk__in=want_false).update(is_backed_up=False)


def list_manga_cbz_files(*, manga_root: str, path: str) -> list[MangaListItem]:
    """``.cbz`` files directly in ``path`` (directory under ``manga_root``). Non-recursive."""
    root_abs = os.path.abspath(os.path.expanduser(manga_root))
    hidden = _manga_hidden_rel_paths()
    if not os.path.isdir(root_abs):
        return []

    rel = normalize_manga_hidden_rel_path(path)
    try:
        base_abs = _path_under_manga_root(manga_root=manga_root, rel_path=rel)
    except ValueError as exc:
        raise ValueError(str(exc)) from exc

    if rel and _directory_hidden_by_config(rel, hidden):
        return []

    if os.path.isfile(base_abs):
        raise ValueError("Path must be a directory")

    if not os.path.isdir(base_abs):
        return []

    base_prefix = rel
    pending: list[tuple[str, str, int, str, datetime | None]] = []

    try:
        names = os.listdir(base_abs)
    except OSError:
        return []

    for fn in names:
        if fn.startswith("."):
            continue
        full = os.path.join(base_abs, fn)
        if not os.path.isfile(full) or not fn.lower().endswith(".cbz"):
            continue
        rel_file_posix = f"{base_prefix}/{fn}" if base_prefix else fn
        parent_posix = posixpath.dirname(rel_file_posix)
        if parent_posix and _directory_hidden_by_config(parent_posix, hidden):
            continue
        rel_path_os = (
            os.path.join(base_prefix.replace("/", os.sep), fn) if base_prefix else fn
        )
        try:
            st = os.stat(full)
        except OSError:
            continue
        file_created_at = _filesystem_created_at_from_stat(st)
        pending.append((fn, rel_path_os, st.st_size, parent_posix, file_created_at))

    dropbox_by_segment: dict[str, list] = {}
    for _name, _rel, _size, parent_posix, _fca in pending:
        seg = _dropbox_list_segment_for_folder(parent_rel=parent_posix)
        if seg not in dropbox_by_segment:
            dropbox_by_segment[seg] = list_dropbox_files(seg)

    out: list[MangaListItem] = []
    for name, rel_path_os, size, parent_posix, file_created_at in pending:
        seg = _dropbox_list_segment_for_folder(parent_rel=parent_posix)
        dfs = dropbox_by_segment[seg]
        is_converted = any(name in df.name for df in dfs)
        out.append(
            MangaListItem(
                name=name,
                path=rel_path_os,
                is_dir=False,
                size=size,
                is_converted=is_converted,
                file_created_at=file_created_at,
            ),
        )
    out.sort(key=lambda i: alphanum_key(i.path.replace(os.sep, "/")))
    return out


def _manga_hidden_rel_paths() -> frozenset[str]:
    from manga.models import MangaHiddenDirectory

    rows = MangaHiddenDirectory.objects.order_by("rel_path").values_list("rel_path", flat=True)
    return frozenset(rows)


def _directory_hidden_by_config(child_rel: str, hidden: frozenset[str]) -> bool:
    for h in hidden:
        if child_rel == h or child_rel.startswith(h + "/"):
            return True
    return False


def _iter_series_rel_paths_with_direct_cbz(
    *,
    manga_root: str,
    hidden: frozenset[str],
) -> list[str]:
    """Paths under ``manga_root`` (POSIX, possibly ``\"\"`` for root) where directory contains ≥1 ``.cbz`` child."""
    root_abs = os.path.abspath(os.path.expanduser(manga_root))
    if not os.path.isdir(root_abs):
        return []

    out: list[str] = []
    stack: list[tuple[str, str]] = [("", root_abs)]

    while stack:
        rel_posix, dir_abs = stack.pop()
        if rel_posix and _directory_hidden_by_config(rel_posix, hidden):
            continue
        try:
            names = os.listdir(dir_abs)
        except OSError:
            continue

        has_cbz = False
        subdirs: list[tuple[str, str]] = []
        for fn in names:
            if fn.startswith("."):
                continue
            full = os.path.join(dir_abs, fn)
            if os.path.isfile(full) and fn.lower().endswith(".cbz"):
                has_cbz = True
            elif os.path.isdir(full):
                child_rel = f"{rel_posix}/{fn}" if rel_posix else fn
                subdirs.append((child_rel, full))

        if has_cbz:
            out.append(rel_posix)

        for child_rel, full in subdirs:
            stack.append((child_rel, full))

    out.sort(key=lambda p: alphanum_key(p))
    return out


def _replace_series_items_from_cbz_listing(
    *,
    manga_root: str,
    series: Series,
    items: list[MangaListItem],
) -> None:
    """Within caller transaction: reconcile ``SeriesItem`` rows with *items* (drop stale, upsert, covers)."""
    want_rel = {i.path.replace("\\", "/") for i in items}
    series.items.exclude(rel_path__in=want_rel).delete()
    for item in items:
        rp = item.path.replace("\\", "/")
        row, _created = SeriesItem.objects.update_or_create(
            series=series,
            rel_path=rp,
            defaults={
                "filename": item.name,
                "size_bytes": item.size,
                "is_converted": item.is_converted,
                "file_created_at": item.file_created_at,
            },
        )
        if item.is_converted and row.dropbox_uploaded_at is None:
            row.dropbox_uploaded_at = timezone.now()
            row.save(update_fields=["dropbox_uploaded_at"])
        elif not item.is_converted and row.dropbox_uploaded_at is not None:
            row.dropbox_uploaded_at = None
            row.save(update_fields=["dropbox_uploaded_at"])
        _refresh_series_item_cover_if_missing(manga_root=manga_root, item=row)

    _refresh_series_cover_from_first_cbz(manga_root=manga_root, series=series)
    series.item_count = series.items.count()
    series.save(update_fields=["item_count"])
    _refresh_series_items_google_drive_backed_up(series=series)


def sync_manga_library_cache(*, manga_root: str) -> tuple[int, int]:
    """Walk filesystem; upsert ``Series`` / ``SeriesItem`` rows (drops vanished).

    Series = directory with ≥1 ``.cbz`` directly inside (same rule as user-facing ``list_manga_cbz_files`` scope).

    Stale series rows removed in one transaction; each series sync commits separately so failure mid-run
    keeps DB updates for series already processed.

    Returns ``(series_count, chapter_count)`` after sync.
    """
    hidden = _manga_hidden_rel_paths()
    root_norm = os.path.abspath(os.path.expanduser(manga_root))
    wanted_paths = set(_iter_series_rel_paths_with_direct_cbz(manga_root=manga_root, hidden=hidden))

    with transaction.atomic():
        stale_qs = Series.objects.filter(library_root=root_norm).exclude(
            series_rel_path__in=wanted_paths,
        )
        stale_ids = list(stale_qs.values_list("pk", flat=True))
        if stale_ids:
            # CbzConvertJob.series is PROTECT; drop jobs for vanished series so stale delete succeeds.
            CbzConvertJob.objects.filter(series_id__in=stale_ids).delete()
        stale_qs.delete()

    for rel_path in sorted(wanted_paths, key=alphanum_key):
        with transaction.atomic():
            display_name = Path(rel_path).name if rel_path else Path(root_norm).name
            series, _created = Series.objects.update_or_create(
                library_root=root_norm,
                series_rel_path=rel_path,
                defaults={"name": display_name},
            )

            items = list_manga_cbz_files(manga_root=manga_root, path=rel_path)
            _replace_series_items_from_cbz_listing(
                manga_root=manga_root,
                series=series,
                items=items,
            )

    series_count = Series.objects.filter(library_root=root_norm).count()
    chapter_total = SeriesItem.objects.filter(series__library_root=root_norm).count()

    return series_count, chapter_total


def sync_series_items_for_cbz_path(*, manga_root: str, cbz_rel_path: str) -> None:
    """Upsert ``Series`` / ``SeriesItem`` for directory containing ``cbz_rel_path`` (Dropbox flags via listing)."""
    rel = normalize_manga_hidden_rel_path(cbz_rel_path)
    series_rel = posixpath.dirname(rel)
    hidden = _manga_hidden_rel_paths()
    if series_rel and _directory_hidden_by_config(series_rel, hidden):
        return

    root_norm = os.path.abspath(os.path.expanduser(manga_root))
    items = list_manga_cbz_files(manga_root=manga_root, path=series_rel)
    display_name = Path(series_rel).name if series_rel else Path(root_norm).name

    with transaction.atomic():
        series, _created = Series.objects.update_or_create(
            library_root=root_norm,
            series_rel_path=series_rel,
            defaults={"name": display_name},
        )
        _replace_series_items_from_cbz_listing(
            manga_root=manga_root,
            series=series,
            items=items,
        )


def sync_series_items_for_series(*, manga_root: str, series_id: int) -> Series:
    """Re-scan one series directory on disk; upsert missing ``SeriesItem`` rows (and prune removed files)."""
    root_norm = os.path.abspath(os.path.expanduser(manga_root))
    try:
        existing = Series.objects.get(pk=series_id, library_root=root_norm)
    except Series.DoesNotExist as exc:
        raise ValueError("Series not found") from exc
    hidden = _manga_hidden_rel_paths()
    srp = existing.series_rel_path
    if srp and _directory_hidden_by_config(srp, hidden):
        raise ValueError("Series path is hidden")
    items = list_manga_cbz_files(manga_root=manga_root, path=srp)
    display_name = Path(srp).name if srp else Path(root_norm).name
    with transaction.atomic():
        series, _created = Series.objects.update_or_create(
            library_root=root_norm,
            series_rel_path=srp,
            defaults={"name": display_name},
        )
        _replace_series_items_from_cbz_listing(
            manga_root=manga_root,
            series=series,
            items=items,
        )
    return Series.objects.select_related("series_info").get(pk=series.pk)


def convert_cbz(
    *,
    manga_root: str,
    item_id: int,
    kind: Literal["manga", "manhwa"],
) -> None:
    """Synchronous CBZ conversion + Dropbox upload (also used by background job)."""
    item = _series_item_for_manga_root(manga_root=manga_root, item_id=item_id)
    path = item.rel_path
    filename = os.path.basename(path)

    if ".cbz" not in filename:
        raise ValueError("Not a CBZ file")

    abs_src = _path_under_manga_root(manga_root=manga_root, rel_path=path)
    work_dir = tempfile.mkdtemp(prefix="manga_convert_")
    try:
        if kind == "manga":
            output_path = process_manga([abs_src], work_dir)
            if output_path is None:
                raise ValueError("Failed to process manga")
        else:
            output_path = process_manhwa_v3([abs_src], work_dir)
            if output_path is None:
                raise ValueError("Failed to process manhwa")

        download_name = dropbox_download_name_for_series_cbz(path, filename)
        upload_bytes = _dropbox_upload_bytes_needed_for_file(output_path)
        with transaction.atomic():
            _dropbox_advisory_lock_xact()
            _ensure_dropbox_space_for_upload(
                manga_root=manga_root,
                reserve_item_id=item.pk,
                upload_bytes=upload_bytes,
            )
            upload_to_dropbox(output_path, path, download_name)
        now = timezone.now()
        SeriesItem.objects.filter(pk=item.pk).update(
            is_converted=True,
            dropbox_uploaded_at=now,
        )
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def create_cbz_convert_job(
    *,
    manga_root: str,
    item_id: int,
    kind: Literal["manga", "manhwa"],
    user_id: int,
) -> int:
    """Create pending ``CbzConvertJob`` and enqueue worker; returns primary key."""
    root_norm = os.path.abspath(os.path.expanduser(manga_root))
    item = _series_item_for_manga_root(manga_root=manga_root, item_id=item_id)
    row = CbzConvertJob.objects.create(
        user_id=user_id,
        manga_root=root_norm,
        series_id=item.series_id,
        series_item_id=item_id,
        kind=kind,
    )
    async_task(
        "manga.scheduled_tasks.run_cbz_convert_job",
        row.pk,
        task_name=f"manga_cbz_convert:{row.pk}",
    )
    return row.pk


def create_google_drive_backup_job(
    *,
    manga_root: str,
    series_id: int,
    user_id: int,
) -> list[int]:
    """Create one pending ``GoogleDriveBackupJob`` per ``SeriesItem`` and enqueue workers.

    Returns primary keys (newest-enqueued last in list; order follows natural ``filename`` sort).
    """
    root_norm = os.path.abspath(os.path.expanduser(manga_root))
    try:
        series = Series.objects.get(pk=series_id, library_root=root_norm)
    except Series.DoesNotExist as exc:
        raise ValueError("Series not found") from exc
    rows = list(series.items.all())
    rows.sort(key=lambda r: alphanum_key(r.filename))
    if not rows:
        raise ValueError("Series has no items")
    job_ids: list[int] = []
    for item in rows:
        row = GoogleDriveBackupJob.objects.create(
            user_id=user_id,
            manga_root=root_norm,
            series_id=series.pk,
            series_item_id=item.pk,
        )
        async_task(
            "manga.scheduled_tasks.run_google_drive_backup_job",
            row.pk,
            task_name=f"manga_gdrive_backup:{row.pk}",
        )
        job_ids.append(row.pk)
    return job_ids


def list_google_drive_backup_jobs(
    *,
    manga_root: str,
    series_id: int | None,
    user_id: int,
    status: str | None = None,
) -> list[GoogleDriveBackupJob]:
    if status is not None and status not in GoogleDriveBackupJobStatus:
        raise ValueError("Invalid status filter.")
    root_norm = os.path.abspath(os.path.expanduser(manga_root))
    qs = GoogleDriveBackupJob.objects.filter(user_id=user_id, manga_root=root_norm)
    if series_id is None:
        qs = qs.filter(series__library_root=root_norm)
    else:
        try:
            series = Series.objects.get(pk=series_id, library_root=root_norm)
        except Series.DoesNotExist as exc:
            raise ValueError("Series not found") from exc
        qs = qs.filter(series_id=series.pk)
    if status is not None:
        qs = qs.filter(status=status)
    return list(qs.order_by("-created_at", "-pk"))


def get_google_drive_backup_job(job_id: int, *, user_id: int) -> GoogleDriveBackupJob:
    return GoogleDriveBackupJob.objects.get(pk=job_id, user_id=user_id)


def _normalize_restore_category(category: str) -> str:
    """Single segment or nested path under manga root; empty = library root (no subfolder)."""
    s = (category or "").strip()
    if not s:
        return ""
    return normalize_manga_hidden_rel_path(s)


def _normalize_restore_series_segment(series_name: str) -> str:
    sn = (series_name or "").strip()
    if not sn or sn in (".", ".."):
        raise ValueError("Invalid series name for restore path")
    if "/" in sn or "\\" in sn:
        raise ValueError("Invalid series name for restore path")
    out = normalize_manga_hidden_rel_path(sn)
    if not out or "/" in out:
        raise ValueError("Invalid series name for restore path")
    return out


def _restore_series_rel_path(
    *,
    manga_root: str,
    category: str,
    series_name: str,
) -> str:
    """Relative path ``category/series_name`` or ``series_name`` when *category* empty."""
    root_norm = os.path.abspath(os.path.expanduser(manga_root))
    cat = _normalize_restore_category(category)
    seg = _normalize_restore_series_segment(series_name)
    if cat:
        srp = normalize_manga_hidden_rel_path(posixpath.join(cat, seg))
    else:
        srp = seg
    try:
        _path_under_manga_root(manga_root=manga_root, rel_path=srp)
    except ValueError as exc:
        raise ValueError("Invalid restore path") from exc
    existing = (
        Series.objects.filter(
            library_root=root_norm,
            name=seg,
            series_rel_path=srp,
        )
        .order_by("pk")
        .first()
    )
    if existing:
        return existing.series_rel_path
    return srp


def _local_file_matches_drive_size(*, abs_path: str, drive_size: int) -> bool:
    if not os.path.isfile(abs_path):
        return False
    if drive_size <= 0:
        return True
    try:
        return os.path.getsize(abs_path) == drive_size
    except OSError:
        return False


def _local_cbz_matches_any_series_with_name(
    *,
    root_norm: str,
    series_name: str,
    filename: str,
    drive_size: int,
) -> bool:
    """True if any ``Series`` with *series_name* under *root_norm* has *filename* at expected size on disk."""
    qs = Series.objects.filter(library_root=root_norm, name=series_name).only("series_rel_path")
    for ser in qs:
        rel = posixpath.join(ser.series_rel_path, filename) if ser.series_rel_path else filename
        abs_p = os.path.join(root_norm, rel.replace("/", os.sep))
        if _local_file_matches_drive_size(abs_path=abs_p, drive_size=drive_size):
            return True
    return False


def list_google_drive_restore_candidates(*, manga_root: str) -> list[dict[str, Any]]:
    """Drive ``Manga/<series>/`` folders vs local CBZs by **series name** (any ``Series`` row path).

    Gaps ignore category: if any cached ``Series`` named like the Drive folder has the file at the right size,
    that chapter counts as present.
    """
    root_norm = os.path.abspath(os.path.expanduser(manga_root))
    manga_folder_id = get_manga_root_drive_folder_id_optional()
    if not manga_folder_id:
        return []
    rows: list[dict[str, Any]] = []
    for folder_id, folder_name in list_child_folder_names_and_ids(parent_folder_id=manga_folder_id):
        drive_cbzs = list_drive_cbz_files_in_folder(parent_folder_id=folder_id)
        drive_total = len(drive_cbzs)
        try:
            seg = _normalize_restore_series_segment(folder_name)
        except ValueError:
            rows.append(
                {
                    "series_name": folder_name,
                    "drive_cbz_count": drive_total,
                    "missing_files": drive_total,
                    "exists_locally": False,
                },
            )
            continue
        exists = Series.objects.filter(library_root=root_norm, name=seg).exists()
        missing = 0
        for ent in drive_cbzs:
            name = ent["name"]
            sz = int(ent.get("size") or 0)
            if _local_cbz_matches_any_series_with_name(
                root_norm=root_norm,
                series_name=seg,
                filename=name,
                drive_size=sz,
            ):
                continue
            missing += 1
        rows.append(
            {
                "series_name": folder_name,
                "drive_cbz_count": drive_total,
                "missing_files": missing,
                "exists_locally": exists,
            },
        )
    rows.sort(key=lambda r: alphanum_key(r["series_name"]))
    return rows


def create_google_drive_restore_job(
    *,
    manga_root: str,
    series_name: str,
    category: str,
    user_id: int,
) -> int:
    """Enqueue full-series restore from Drive backup folder name; returns ``GoogleDriveRestoreJob`` pk.

    Files are written to ``<manga_root>/<category>/<series_name>/*.cbz``.
    """
    name = (series_name or "").strip()
    if not name:
        raise ValueError("series_name must be non-empty")
    cat_in = (category or "").strip()
    if not cat_in:
        raise ValueError("category must be non-empty")
    cat_norm = _normalize_restore_category(cat_in)
    if not cat_norm:
        raise ValueError("category must be non-empty")
    root_norm = os.path.abspath(os.path.expanduser(manga_root))
    folder_id = get_series_drive_folder_id_optional(series_name=name)
    if not folder_id:
        raise ValueError("Series not found on Google Drive")
    if not list_drive_cbz_files_in_folder(parent_folder_id=folder_id):
        raise ValueError("No CBZ files in Drive folder for this series")
    try:
        _restore_series_rel_path(manga_root=manga_root, category=cat_norm, series_name=name)
    except ValueError as exc:
        raise ValueError(str(exc)) from exc

    row = GoogleDriveRestoreJob.objects.create(
        user_id=user_id,
        manga_root=root_norm,
        series_name=name,
        category=cat_norm,
    )
    async_task(
        "manga.scheduled_tasks.run_google_drive_restore_job",
        row.pk,
        task_name=f"manga_gdrive_restore:{row.pk}",
    )
    return row.pk


def get_google_drive_restore_job(job_id: int, *, user_id: int) -> GoogleDriveRestoreJob:
    return GoogleDriveRestoreJob.objects.get(pk=job_id, user_id=user_id)


def run_google_drive_restore_job(*, job_id: int) -> None:
    """Background worker: download Drive CBZs into library and rescan ``Series`` / ``SeriesItem``."""
    try:
        job = GoogleDriveRestoreJob.objects.get(pk=job_id)
    except GoogleDriveRestoreJob.DoesNotExist:
        logger.warning("run_google_drive_restore_job: missing GoogleDriveRestoreJob id=%s", job_id)
        return
    root_norm = job.manga_root
    series_label = job.series_name.strip()
    category_label = (job.category or "").strip()
    try:
        folder_id = get_series_drive_folder_id_optional(series_name=series_label)
        if not folder_id:
            raise ValueError("Series folder not found on Google Drive")
        drive_files = list_drive_cbz_files_in_folder(parent_folder_id=folder_id)
        if not drive_files:
            raise ValueError("No CBZ files in Drive folder")

        series_rel = _restore_series_rel_path(
            manga_root=root_norm,
            category=category_label,
            series_name=series_label,
        )
        abs_dir = _path_under_manga_root(manga_root=root_norm, rel_path=series_rel)
        os.makedirs(abs_dir, exist_ok=True)

        for ent in drive_files:
            fname = ent["name"]
            fid = ent["id"]
            sz = int(ent.get("size") or 0)
            rel_one = posixpath.join(series_rel, fname) if series_rel else fname
            abs_cbz = _path_under_manga_root(manga_root=root_norm, rel_path=rel_one)
            if _local_file_matches_drive_size(abs_path=abs_cbz, drive_size=sz):
                continue
            part_path = abs_cbz + ".part"
            try:
                download_drive_file_to_path(file_id=fid, dest_path=part_path)
                os.replace(part_path, abs_cbz)
            except Exception:
                if os.path.isfile(part_path):
                    try:
                        os.unlink(part_path)
                    except OSError:
                        pass
                raise

        with transaction.atomic():
            series, _created = Series.objects.update_or_create(
                library_root=root_norm,
                series_rel_path=series_rel,
                defaults={"name": _normalize_restore_series_segment(series_label)},
            )
        sync_series_items_for_series(manga_root=root_norm, series_id=series.pk)

        job.status = GoogleDriveRestoreJobStatus.COMPLETED
        job.completed_at = timezone.now()
        job.failure_message = None
        job.save(update_fields=["status", "completed_at", "failure_message"])
    except Exception as exc:
        logger.exception("run_google_drive_restore_job failed (job id=%s)", job_id)
        job.status = GoogleDriveRestoreJobStatus.FAILED
        job.completed_at = timezone.now()
        job.failure_message = drive_http_error_message(exc)
        job.save(update_fields=["status", "completed_at", "failure_message"])


def list_cbz_convert_jobs(
    *,
    manga_root: str,
    series_id: int | None,
    user_id: int,
    status: str | None = None,
) -> list[CbzConvertJob]:
    """Convert jobs for *user_id* under *manga_root*.

    *series_id* set: jobs for that series (must exist in library).
    *series_id* null: jobs in library (``series.library_root`` matches *manga_root*).

    Newest first. Optional *status* limits to that job status value.
    Raises ``ValueError("Series not found")`` when *series_id* set and series missing or wrong library.
    Raises ``ValueError("Invalid status filter.")`` when *status* is not a known status.
    """
    if status is not None and status not in CbzConvertJobStatus:
        raise ValueError("Invalid status filter.")
    root_norm = os.path.abspath(os.path.expanduser(manga_root))
    qs = CbzConvertJob.objects.filter(user_id=user_id, manga_root=root_norm)
    if series_id is None:
        qs = qs.filter(series__library_root=root_norm)
    else:
        try:
            series = Series.objects.get(pk=series_id, library_root=root_norm)
        except Series.DoesNotExist as exc:
            raise ValueError("Series not found") from exc
        qs = qs.filter(series_id=series.pk)
    if status is not None:
        qs = qs.filter(status=status)
    return list(qs.order_by("-created_at", "-pk"))


def get_cbz_convert_job(job_id: int, *, user_id: int) -> CbzConvertJob:
    return CbzConvertJob.objects.get(pk=job_id, user_id=user_id)


def _mangabaka_title_match_threshold() -> int:
    return int(getattr(settings, "MANGABAKA_TITLE_MATCH_THRESHOLD", 90))


def _mangabaka_info_batch_size() -> int:
    return max(1, int(getattr(settings, "MANGABAKA_INFO_SYNC_BATCH_SIZE", 5)))


def _mangabaka_http_delay_seconds() -> float:
    return float(getattr(settings, "MANGABAKA_HTTP_DELAY_SECONDS", 0.5))


def _mangabaka_search_limit() -> int:
    return max(3, min(25, int(getattr(settings, "MANGABAKA_SEARCH_LIMIT", 12))))


def _normalize_mangabaka_search_query(query: str) -> str:
    s = query.strip()
    if not s:
        raise ValueError("query must be a non-empty string")
    return s


def _parse_mangabaka_search_hits(hits: list[dict]) -> list[dict[str, Any]]:
    """Build serializable rows with ``mangabaka_series_id`` + ``title`` for each valid API hit."""
    out: list[dict[str, Any]] = []
    for row in hits:
        if not isinstance(row, dict):
            continue
        title = row.get("title")
        if not isinstance(title, str) or not title.strip():
            continue
        sid = row.get("id")
        if isinstance(sid, str) and sid.isdigit():
            sid = int(sid)
        if not isinstance(sid, int) or sid < 1:
            continue
        out.append({"mangabaka_series_id": sid, "title": title})
    return out


_MANGABAKA_PUBLIC_SEARCH_MAX = 20


def search_mangabaka_series(*, query: str) -> list[dict[str, Any]]:
    """Call MangaBaka ``/v1/series/search``; at most 20 hits (no pagination)."""
    q = _normalize_mangabaka_search_query(query)
    raw_hits, _pag = search_series(query=q, limit=_MANGABAKA_PUBLIC_SEARCH_MAX, page=1)
    parsed = _parse_mangabaka_search_hits(raw_hits)
    return parsed[:_MANGABAKA_PUBLIC_SEARCH_MAX]


def _mangabaka_no_match_snooze_hours() -> int:
    return max(1, int(getattr(settings, "MANGABAKA_NO_MATCH_SNOOZE_HOURS", 24)))


def _pick_mangabaka_series_id_from_search_hits(
    *,
    local_name: str,
    hits: list[dict],
) -> int | None:
    """Return best matching MangaBaka id, or None when no hit clears fuzzy threshold."""
    if not local_name.strip():
        return None
    threshold = _mangabaka_title_match_threshold()
    best_id: int | None = None
    best_score = -1
    needle = local_name.strip().lower()
    for row in hits:
        title = row.get("title")
        if not isinstance(title, str) or not title.strip():
            continue
        sid = row.get("id")
        if isinstance(sid, str) and sid.isdigit():
            sid = int(sid)
        if not isinstance(sid, int) or sid < 1:
            continue
        score = fuzz.ratio(needle, title.strip().lower())
        if score > best_score:
            best_score = score
            best_id = sid
    if best_id is None or best_score < threshold:
        return None
    return best_id


def _normalize_mangabaka_rating(raw: object) -> int | None:
    if raw is None:
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float):
        return int(round(raw))
    return None


def _apply_mangabaka_detail_to_series_info(*, info: SeriesInfo, detail: dict) -> None:
    desc = detail.get("description")
    description = desc.strip() if isinstance(desc, str) else ""
    rating = _normalize_mangabaka_rating(detail.get("rating"))
    raw_type = detail.get("type")
    if isinstance(raw_type, str):
        series_type = raw_type.strip()[:64]
    elif raw_type is None:
        series_type = ""
    else:
        series_type = str(raw_type).strip()[:64]
    info.description = description
    info.rating = rating
    info.series_type = series_type
    info.is_complete = True
    info.synced_at = timezone.now()
    info.save(
        update_fields=[
            "description",
            "rating",
            "series_type",
            "is_complete",
            "synced_at",
        ],
    )


def set_series_mangabaka_series_id(
    *,
    manga_root: str,
    series_id: int,
    mangabaka_series_id: int,
) -> Series:
    """Set ``SeriesInfo.mangabaka_series_id`` from user input and fill metadata from MangaBaka detail API."""
    get_series(manga_root=manga_root, series_id=series_id)
    root_norm = os.path.abspath(os.path.expanduser(manga_root))
    detail = fetch_series_detail(series_id=mangabaka_series_id)

    with transaction.atomic():
        locked = Series.objects.select_for_update().get(pk=series_id, library_root=root_norm)
        try:
            info = SeriesInfo.objects.select_for_update(of=("self",)).get(series_id=locked.pk)
        except SeriesInfo.DoesNotExist:
            info = SeriesInfo.objects.create(
                series=locked,
                mangabaka_series_id=mangabaka_series_id,
                description="",
                rating=None,
                is_complete=False,
            )
        else:
            info.mangabaka_series_id = mangabaka_series_id
            info.save(update_fields=["mangabaka_series_id"])

        _apply_mangabaka_detail_to_series_info(info=info, detail=detail)

        if locked.mangabaka_search_snoozed_until is not None:
            locked.mangabaka_search_snoozed_until = None
            locked.save(update_fields=["mangabaka_search_snoozed_until"])

    return Series.objects.select_related("series_info").get(pk=series_id, library_root=root_norm)


def refresh_series_info_from_mangabaka(*, manga_root: str, series_id: int) -> Series:
    """Re-fetch MangaBaka detail for *series_id* when ``SeriesInfo.mangabaka_series_id`` already set.

    Does not run title search (unlike scheduled sync). Raises ``ValueError`` when no linked id.
    """
    root_norm = os.path.abspath(os.path.expanduser(manga_root))
    get_series(manga_root=manga_root, series_id=series_id)
    while True:
        try:
            probe = SeriesInfo.objects.get(series_id=series_id)
        except SeriesInfo.DoesNotExist as exc:
            raise ValueError("Series has no MangaBaka link yet") from exc
        if probe.mangabaka_series_id is None:
            raise ValueError("Series has no MangaBaka link yet")
        mb_id = probe.mangabaka_series_id
        detail = fetch_series_detail(series_id=mb_id)
        with transaction.atomic():
            locked = Series.objects.select_for_update().get(pk=series_id, library_root=root_norm)
            try:
                info = SeriesInfo.objects.select_for_update(of=("self",)).get(series_id=locked.pk)
            except SeriesInfo.DoesNotExist as exc:
                raise ValueError("Series has no MangaBaka link yet") from exc
            if info.mangabaka_series_id is None:
                raise ValueError("Series has no MangaBaka link yet")
            if info.mangabaka_series_id != mb_id:
                continue
            _apply_mangabaka_detail_to_series_info(info=info, detail=detail)
            break
    return Series.objects.select_related("series_info").get(pk=series_id, library_root=root_norm)


def sync_manga_series_info_from_mangabaka() -> int:
    """Fill ``SeriesInfo`` from MangaBaka API for a small batch of series missing complete metadata.

    ``SeriesInfo`` rows exist only after a confident title match; no-match uses
    ``Series.mangabaka_search_snoozed_until`` on the parent series. Skips series with complete
    info or active snooze. Detail-fetch errors retry each run.
    Returns number of series rows processed this run.
    """
    batch = _mangabaka_info_batch_size()
    delay = _mangabaka_http_delay_seconds()
    search_limit = _mangabaka_search_limit()
    now = timezone.now()
    skip_done = SeriesInfo.objects.filter(
        series_id=OuterRef("pk"),
        is_complete=True,
        mangabaka_series_id__isnull=False,
    )
    candidates = (
        Series.objects.filter(~Exists(skip_done))
        .filter(
            Q(mangabaka_search_snoozed_until__isnull=True)
            | Q(mangabaka_search_snoozed_until__lte=now),
        )
        .order_by("library_root", "name", "series_rel_path", "pk")[:batch]
    )
    processed = 0
    for series in candidates:
        processed += 1
        try:
            _sync_single_series_info_from_mangabaka(
                series=series,
                search_limit=search_limit,
            )
        except Exception:
            logger.exception(
                "MangaBaka series info sync failed for series id=%s name=%r",
                series.pk,
                series.name,
            )
        if delay > 0:
            time.sleep(delay)
    return processed


@transaction.atomic
def _sync_single_series_info_from_mangabaka(*, series: Series, search_limit: int) -> None:
    locked = Series.objects.select_for_update().get(pk=series.pk)
    now = timezone.now()
    if (
        locked.mangabaka_search_snoozed_until is not None
        and locked.mangabaka_search_snoozed_until > now
    ):
        return

    try:
        info = SeriesInfo.objects.select_for_update(of=("self",)).get(series_id=locked.pk)
    except SeriesInfo.DoesNotExist:
        info = None

    if info is not None and info.is_complete and info.mangabaka_series_id is not None:
        return

    mb_id = info.mangabaka_series_id if info else None
    if mb_id is None:
        hits, _pag = search_series(query=locked.name.strip(), limit=search_limit, page=1)
        mb_id = _pick_mangabaka_series_id_from_search_hits(local_name=locked.name, hits=hits)
        if mb_id is None:
            locked.mangabaka_search_snoozed_until = now + timedelta(
                hours=_mangabaka_no_match_snooze_hours(),
            )
            locked.save(update_fields=["mangabaka_search_snoozed_until"])
            return
        if info is None:
            SeriesInfo.objects.create(
                series=locked,
                mangabaka_series_id=mb_id,
                description="",
                rating=None,
                is_complete=False,
            )
        else:
            info.mangabaka_series_id = mb_id
            info.save(update_fields=["mangabaka_series_id"])
        if locked.mangabaka_search_snoozed_until is not None:
            locked.mangabaka_search_snoozed_until = None
            locked.save(update_fields=["mangabaka_search_snoozed_until"])
        info = SeriesInfo.objects.select_for_update(of=("self",)).get(series_id=locked.pk)

    try:
        detail = fetch_series_detail(series_id=info.mangabaka_series_id)
    except MangaBakaAPIError as exc:
        logger.warning(
            "MangaBaka detail fetch failed series pk=%s mb_id=%s: %s",
            locked.pk,
            info.mangabaka_series_id,
            exc,
        )
        return

    _apply_mangabaka_detail_to_series_info(info=info, detail=detail)


def run_cbz_convert_job(*, job_id: int) -> None:
    """Background worker: ``convert_cbz`` using stored ``manga_root`` / ``series_item_id``."""
    try:
        job = CbzConvertJob.objects.get(pk=job_id)
    except CbzConvertJob.DoesNotExist:
        logger.warning("run_cbz_convert_job: missing CbzConvertJob id=%s", job_id)
        return
    kind: Literal["manga", "manhwa"] = (
        "manhwa" if job.kind == CbzConvertKind.MANHWA else "manga"
    )
    try:
        convert_cbz(
            manga_root=job.manga_root,
            item_id=job.series_item_id,
            kind=kind,
        )
        job.status = CbzConvertJobStatus.COMPLETED
        job.completed_at = timezone.now()
        job.failure_message = None
        job.save(update_fields=["status", "completed_at", "failure_message"])
    except Exception as exc:
        logger.exception("run_cbz_convert_job failed (job id=%s)", job_id)
        job.status = CbzConvertJobStatus.FAILED
        job.completed_at = timezone.now()
        job.failure_message = str(exc) or exc.__class__.__name__
        job.save(update_fields=["status", "completed_at", "failure_message"])


def run_google_drive_backup_job(*, job_id: int) -> None:
    """Background worker: upload CBZ into ``Manga/<series name>/`` (root name from settings)."""
    try:
        job = GoogleDriveBackupJob.objects.select_related("series").get(pk=job_id)
    except GoogleDriveBackupJob.DoesNotExist:
        logger.warning("run_google_drive_backup_job: missing GoogleDriveBackupJob id=%s", job_id)
        return
    try:
        item = SeriesItem.objects.get(pk=job.series_item_id, series_id=job.series_id)
    except SeriesItem.DoesNotExist:
        job.status = GoogleDriveBackupJobStatus.FAILED
        job.completed_at = timezone.now()
        job.failure_message = "SeriesItem not found"
        job.save(update_fields=["status", "completed_at", "failure_message"])
        return
    try:
        resolved = resolve_cbz_download(manga_root=job.manga_root, item_id=item.pk)
        folder_id = ensure_series_drive_folder(series_name=job.series.name)
        try:
            local_size = os.path.getsize(resolved.absolute_path)
        except OSError as exc:
            raise ValueError(f"Cannot read local file size: {exc}") from exc
        existing_id = find_existing_file_id_with_same_size(
            parent_folder_id=folder_id,
            drive_filename=resolved.filename,
            expected_size=local_size,
        )
        if existing_id:
            logger.info(
                "Drive backup skip (same name+size): job=%s file=%s id=%s",
                job_id,
                resolved.filename,
                existing_id,
            )
            file_id = existing_id
        else:
            file_id = upload_file_to_folder(
                local_path=resolved.absolute_path,
                drive_filename=resolved.filename,
                parent_folder_id=folder_id,
            )
        job.status = GoogleDriveBackupJobStatus.COMPLETED
        job.completed_at = timezone.now()
        job.failure_message = None
        job.google_drive_file_id = file_id
        job.save(
            update_fields=[
                "status",
                "completed_at",
                "failure_message",
                "google_drive_file_id",
            ],
        )
        SeriesItem.objects.filter(pk=item.pk).update(is_backed_up=True)
    except Exception as exc:
        logger.exception("run_google_drive_backup_job failed (job id=%s)", job_id)
        job.status = GoogleDriveBackupJobStatus.FAILED
        job.completed_at = timezone.now()
        job.failure_message = drive_http_error_message(exc)
        job.save(update_fields=["status", "completed_at", "failure_message"])
