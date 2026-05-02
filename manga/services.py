import os
from dataclasses import dataclass
from typing import Literal

from manga.cbztools.manga_v2 import process_manga
from manga.cbztools.manhwa_v3 import process_manhwa_v3
from manga.cbztools.utils import list_dropbox_files, sort_nicely, upload_to_dropbox


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
    children: tuple["MangaDirectoryNode", ...]


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


def list_manga_directories(*, manga_root: str) -> MangaDirectoryNode:
    """Nested directory tree under manga_root (directories only)."""
    if not os.path.isdir(manga_root):
        return MangaDirectoryNode(name="", path="", children=())
    return _manga_directory_subtree(os.path.abspath(manga_root), rel_posix="")


def _manga_directory_subtree(full_path: str, *, rel_posix: str) -> MangaDirectoryNode:
    name = "" if not rel_posix else rel_posix.split("/")[-1]
    entries = [e for e in os.listdir(full_path) if not e.startswith(".")]
    dirs_only = [e for e in entries if os.path.isdir(os.path.join(full_path, e))]
    sort_nicely(dirs_only)
    children: list[MangaDirectoryNode] = []
    for d in dirs_only:
        child_rel = f"{rel_posix}/{d}" if rel_posix else d
        child_full = os.path.join(full_path, d)
        children.append(_manga_directory_subtree(child_full, rel_posix=child_rel))
    return MangaDirectoryNode(name=name, path=rel_posix, children=tuple(children))


def convert_cbz(
    *,
    manga_root: str,
    path: str,
    kind: Literal["manga", "manhwa"],
) -> None:
    filename = os.path.basename(path)

    if ".cbz" not in filename:
        raise ValueError("Not a CBZ file")

    abs_src = os.path.join(manga_root, path)
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
