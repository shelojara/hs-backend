import os
import posixpath
from dataclasses import dataclass
from typing import Literal

import hashlib

from django.conf import settings
from django.core.cache import cache

from manga.cbztools.manga_v2 import process_manga
from manga.cbztools.manhwa_v3 import process_manhwa_v3
from manga.cbztools.utils import (
    alphanum_key,
    list_dropbox_files,
    sort_nicely,
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
class MangaDirectoryNode:
    name: str
    path: str
    parent_name: str
    children: tuple["MangaDirectoryNode", ...]


@dataclass(frozen=True)
class CbzDownload:
    """Resolved on-disk CBZ for streaming to client."""

    absolute_path: str
    filename: str


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


def resolve_cbz_download(*, manga_root: str, path: str) -> CbzDownload:
    """Resolve relative path to a readable .cbz under manga_root."""
    filename = os.path.basename(path)
    if not filename.lower().endswith(".cbz"):
        raise ValueError("Not a CBZ file")
    abs_path = _path_under_manga_root(manga_root=manga_root, rel_path=path)
    if not os.path.isfile(abs_path):
        raise ValueError("CBZ not found")
    return CbzDownload(absolute_path=abs_path, filename=filename)


def list_manga_items(*, manga_root: str, path: str) -> list[MangaListItem]:
    full_path = os.path.join(manga_root, path)
    children = os.listdir(full_path)
    children = [f for f in children if not f.startswith(".")]
    sort_nicely(children)
    items = [
        MangaListItem(
            name=f,
            path=os.path.join(path, f),
            is_dir=os.path.isdir(os.path.join(full_path, f)),
            size=(
                os.path.getsize(os.path.join(full_path, f))
                if os.path.isfile(os.path.join(full_path, f))
                else None
            ),
            in_dropbox=False,
        )
        for f in children
    ]

    dropbox_files = list_dropbox_files(os.path.split(path)[-1])
    flagged = []
    for item in items:
        in_dropbox = any(item.name in df.name for df in dropbox_files)
        flagged.append(
            MangaListItem(
                name=item.name,
                path=item.path,
                is_dir=item.is_dir,
                size=item.size,
                in_dropbox=in_dropbox,
            )
        )
    return flagged


_MANGA_DIRECTORIES_CACHE_KEY = "manga:directories:v6:{root}:{hidden_fp}:{ver}"


def _manga_directories_ver_key(manga_root: str) -> str:
    root = os.path.abspath(os.path.expanduser(manga_root))
    return f"manga:directories:ver:{root}"


def _manga_directories_cache_ver(manga_root: str) -> int:
    v = cache.get(_manga_directories_ver_key(manga_root))
    return int(v) if v is not None else 0


def _bump_manga_directories_cache_ver(manga_root: str) -> None:
    k = _manga_directories_ver_key(manga_root)
    n = _manga_directories_cache_ver(manga_root) + 1
    # Long TTL: version only advances; stale entries harmless after tree keys expire.
    cache.set(k, n, timeout=86400 * 365)


def _manga_hidden_rel_paths() -> frozenset[str]:
    from manga.models import MangaHiddenDirectory

    rows = MangaHiddenDirectory.objects.order_by("rel_path").values_list("rel_path", flat=True)
    return frozenset(rows)


def _hidden_paths_fingerprint(hidden: frozenset[str]) -> str:
    if not hidden:
        return "none"
    joined = "\n".join(sorted(hidden))
    return hashlib.sha256(joined.encode()).hexdigest()[:16]


def _manga_directories_cache_key(manga_root: str, *, hidden: frozenset[str]) -> str:
    root = os.path.abspath(os.path.expanduser(manga_root))
    fp = _hidden_paths_fingerprint(hidden)
    ver = _manga_directories_cache_ver(manga_root)
    return _MANGA_DIRECTORIES_CACHE_KEY.format(root=root, hidden_fp=fp, ver=ver)


def _directory_hidden_by_config(child_rel: str, hidden: frozenset[str]) -> bool:
    for h in hidden:
        if child_rel == h or child_rel.startswith(h + "/"):
            return True
    return False


def invalidate_manga_directories_cache(*, manga_root: str) -> None:
    """Invalidate cached directory tree for manga_root (filesystem or hidden-path config change)."""
    _bump_manga_directories_cache_ver(manga_root)


def _promote_top_level_directory_children(
    node: MangaDirectoryNode,
    *,
    hidden: frozenset[str],
) -> MangaDirectoryNode:
    """Under manga root, list grandchildren when top-level folder has subdirs; else keep folder."""
    if node.path != "" or node.name != "":
        return node
    promoted: list[MangaDirectoryNode] = []
    for top in node.children:
        if top.path and _directory_hidden_by_config(top.path, hidden):
            continue
        if top.children:
            promoted.extend(top.children)
        else:
            promoted.append(top)
    promoted.sort(key=lambda n: (alphanum_key(n.name), n.path))
    return MangaDirectoryNode(name="", path="", parent_name="", children=tuple(promoted))


def _strip_hidden_directory_nodes(
    node: MangaDirectoryNode,
    *,
    hidden: frozenset[str],
) -> MangaDirectoryNode | None:
    """Drop directory subtrees whose path matches hidden config (needed after promotion)."""
    if node.path and _directory_hidden_by_config(node.path, hidden):
        return None
    kept: list[MangaDirectoryNode] = []
    for c in node.children:
        stripped = _strip_hidden_directory_nodes(c, hidden=hidden)
        if stripped is not None:
            kept.append(stripped)
    return MangaDirectoryNode(
        name=node.name,
        path=node.path,
        parent_name=node.parent_name,
        children=tuple(kept),
    )


def list_manga_series(*, manga_root: str) -> MangaDirectoryNode:
    """Nested directory tree under manga_root (directories only).

    Immediate children of manga root are not listed as nodes when they contain
    subdirectories; those subdirectories appear at the root of the tree instead.
    Hidden-path rules apply to promoted paths as well as top-level directories.
    """
    hidden = _manga_hidden_rel_paths()
    key = _manga_directories_cache_key(manga_root, hidden=hidden)
    cached = cache.get(key)
    if cached is not None:
        return cached
    if not os.path.isdir(manga_root):
        node = MangaDirectoryNode(name="", path="", parent_name="", children=())
    else:
        raw = _manga_directory_subtree(
            os.path.abspath(manga_root),
            rel_posix="",
            hidden=hidden,
        )
        promoted = _promote_top_level_directory_children(raw, hidden=hidden)
        stripped = _strip_hidden_directory_nodes(promoted, hidden=hidden)
        node = (
            stripped
            if stripped is not None
            else MangaDirectoryNode(name="", path="", parent_name="", children=())
        )
    timeout = getattr(settings, "MANGA_DIRECTORIES_CACHE_TIMEOUT_SECONDS", 300)
    cache.set(key, node, timeout=timeout)
    return node


def _manga_directory_subtree(
    full_path: str,
    *,
    rel_posix: str,
    hidden: frozenset[str],
) -> MangaDirectoryNode:
    name = "" if not rel_posix else rel_posix.split("/")[-1]
    parent_name = (
        posixpath.basename(posixpath.dirname(rel_posix)) if rel_posix else ""
    )
    entries = [e for e in os.listdir(full_path) if not e.startswith(".")]
    dirs_only = [e for e in entries if os.path.isdir(os.path.join(full_path, e))]
    sort_nicely(dirs_only)
    children: list[MangaDirectoryNode] = []
    for d in dirs_only:
        child_rel = f"{rel_posix}/{d}" if rel_posix else d
        if _directory_hidden_by_config(child_rel, hidden):
            continue
        child_full = os.path.join(full_path, d)
        children.append(
            _manga_directory_subtree(child_full, rel_posix=child_rel, hidden=hidden),
        )
    return MangaDirectoryNode(
        name=name,
        path=rel_posix,
        parent_name=parent_name,
        children=tuple(children),
    )


def convert_cbz(
    *,
    manga_root: str,
    path: str,
    kind: Literal["manga", "manhwa"],
) -> None:
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
    invalidate_manga_directories_cache(manga_root=manga_root)
