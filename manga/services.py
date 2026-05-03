import base64
import logging
import os
import posixpath
from datetime import UTC, datetime
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import BinaryIO, Literal

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django_q.tasks import async_task
from PIL import Image

from manga.cbztools.manga_v2 import process_manga
from manga.cbztools.manhwa_v3 import process_manhwa_v3
from manga.cbztools.utils import (
    alphanum_key,
    is_image,
    list_dropbox_files,
    upload_to_dropbox,
)
from manga.models import (
    CbzConvertJob,
    CbzConvertJobStatus,
    CbzConvertKind,
    Series,
    SeriesItem,
    normalize_manga_hidden_rel_path,
)

logger = logging.getLogger(__name__)


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
    in_dropbox: bool
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
    return list(qs[offset : offset + limit])


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
    in_dropbox: bool | None = None,
) -> list[SeriesItem]:
    """Query ``SeriesItem`` for ``series_id`` under ``manga_root`` (natural order by ``filename``)."""
    root_norm = os.path.abspath(os.path.expanduser(manga_root))
    try:
        series = Series.objects.get(pk=series_id, library_root=root_norm)
    except Series.DoesNotExist as exc:
        raise ValueError("Series not found") from exc
    qs = series.items.all()
    if in_dropbox is not None:
        qs = qs.filter(in_dropbox=in_dropbox)
    rows = list(qs)
    rows.sort(key=lambda r: alphanum_key(r.filename))
    return rows[offset : offset + limit]


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


def _series_item_for_manga_root(*, manga_root: str, item_id: int) -> SeriesItem:
    root_norm = os.path.abspath(os.path.expanduser(manga_root))
    try:
        item = SeriesItem.objects.select_related("series").get(pk=item_id)
    except SeriesItem.DoesNotExist:
        raise ValueError("Item not found") from None
    if item.series.library_root != root_norm:
        raise ValueError("Item not found") from None
    return item


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
        in_dropbox = any(name in df.name for df in dfs)
        out.append(
            MangaListItem(
                name=name,
                path=rel_path_os,
                is_dir=False,
                size=size,
                in_dropbox=in_dropbox,
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
                        "in_dropbox": item.in_dropbox,
                        "file_created_at": item.file_created_at,
                    },
                )
                if item.in_dropbox and row.dropbox_uploaded_at is None:
                    row.dropbox_uploaded_at = timezone.now()
                    row.save(update_fields=["dropbox_uploaded_at"])
                elif not item.in_dropbox and row.dropbox_uploaded_at is not None:
                    row.dropbox_uploaded_at = None
                    row.save(update_fields=["dropbox_uploaded_at"])
                _refresh_series_item_cover_if_missing(manga_root=manga_root, item=row)

            _refresh_series_cover_from_first_cbz(manga_root=manga_root, series=series)
            series.item_count = series.items.count()
            series.save(update_fields=["item_count"])

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
                    "in_dropbox": item.in_dropbox,
                    "file_created_at": item.file_created_at,
                },
            )
            if item.in_dropbox and row.dropbox_uploaded_at is None:
                row.dropbox_uploaded_at = timezone.now()
                row.save(update_fields=["dropbox_uploaded_at"])
            elif not item.in_dropbox and row.dropbox_uploaded_at is not None:
                row.dropbox_uploaded_at = None
                row.save(update_fields=["dropbox_uploaded_at"])
            _refresh_series_item_cover_if_missing(manga_root=manga_root, item=row)

        _refresh_series_cover_from_first_cbz(manga_root=manga_root, series=series)
        series.item_count = series.items.count()
        series.save(update_fields=["item_count"])


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

        parent_dir = os.path.basename(os.path.dirname(path))
        basename, ext = os.path.splitext(filename)
        download_name = basename
        if parent_dir not in basename:
            download_name = f"{parent_dir} - {basename}"
        download_name += ext

        upload_to_dropbox(output_path, path, download_name)
        now = timezone.now()
        SeriesItem.objects.filter(pk=item.pk).update(
            in_dropbox=True,
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
