import os
import posixpath
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Literal

from django.db import transaction

from manga.models import Series, SeriesItem, normalize_manga_hidden_rel_path
from manga.cbztools.manga_v2 import process_manga
from manga.cbztools.manhwa_v3 import process_manhwa_v3
from manga.cbztools.utils import (
    alphanum_key,
    is_image,
    list_dropbox_files,
    upload_to_dropbox,
)


@dataclass(frozen=True)
class MangaListItem:
    name: str
    path: str
    is_dir: bool
    size: int | None
    in_dropbox: bool


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
) -> list[Series]:
    """Query ``Series`` for ``manga_root`` (normalized), ordered by display ``name``."""
    root_norm = os.path.abspath(os.path.expanduser(manga_root))
    qs = Series.objects.filter(library_root=root_norm).order_by("name", "series_rel_path")
    return list(qs[offset : offset + limit])


def list_series_items(
    *,
    manga_root: str,
    series_id: int,
    limit: int = 100,
    offset: int = 0,
) -> list[SeriesItem]:
    """Query ``SeriesItem`` for ``series_id`` under ``manga_root`` (natural order by ``filename``)."""
    root_norm = os.path.abspath(os.path.expanduser(manga_root))
    try:
        series = Series.objects.get(pk=series_id, library_root=root_norm)
    except Series.DoesNotExist as exc:
        raise ValueError("Series not found") from exc
    rows = list(series.items.all())
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
    pending: list[tuple[str, str, int, str]] = []

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
        pending.append((fn, rel_path_os, os.path.getsize(full), parent_posix))

    dropbox_by_segment: dict[str, list] = {}
    for _name, _rel, _size, parent_posix in pending:
        seg = _dropbox_list_segment_for_folder(parent_rel=parent_posix)
        if seg not in dropbox_by_segment:
            dropbox_by_segment[seg] = list_dropbox_files(seg)

    out: list[MangaListItem] = []
    for name, rel_path_os, size, parent_posix in pending:
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
                SeriesItem.objects.update_or_create(
                    series=series,
                    rel_path=rp,
                    defaults={
                        "filename": item.name,
                        "size_bytes": item.size,
                        "in_dropbox": item.in_dropbox,
                    },
                )

        series_count = Series.objects.filter(library_root=root_norm).count()
        chapter_total = SeriesItem.objects.filter(series__library_root=root_norm).count()

    return series_count, chapter_total


def sync_series_items_for_cbz_path(*, manga_root: str, cbz_rel_path: str) -> None:
    """Upsert ``Series`` / ``SeriesItem`` for directory containing ``cbz_rel_path`` (Dropbox flags via listing).

    Used after ``convert_cbz`` upload so DB tracks Dropbox state without full-library ``sync_manga_library_cache``.
    """
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
            SeriesItem.objects.update_or_create(
                series=series,
                rel_path=rp,
                defaults={
                    "filename": item.name,
                    "size_bytes": item.size,
                    "in_dropbox": item.in_dropbox,
                },
            )


def convert_cbz(
    *,
    manga_root: str,
    item_id: int,
    kind: Literal["manga", "manhwa"],
) -> None:
    item = _series_item_for_manga_root(manga_root=manga_root, item_id=item_id)
    path = item.rel_path
    filename = os.path.basename(path)

    if ".cbz" not in filename:
        raise ValueError("Not a CBZ file")

    abs_src = _path_under_manga_root(manga_root=manga_root, rel_path=path)
    if kind == "manga":
        output_path = process_manga([abs_src])
        if output_path is None:
            raise ValueError("Failed to process manga")
    else:
        output_path = process_manhwa_v3([abs_src])
        if output_path is None:
            raise ValueError("Failed to process manhwa")

    parent_dir = os.path.basename(os.path.dirname(path))
    basename, ext = os.path.splitext(filename)
    download_name = basename
    if parent_dir not in basename:
        download_name = f"{parent_dir} - {basename}"
    download_name += ext

    upload_to_dropbox(output_path, path, download_name)
    sync_series_items_for_cbz_path(manga_root=manga_root, cbz_rel_path=path)
