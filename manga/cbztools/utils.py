import os
import re
import shutil

import dropbox
from dropbox.exceptions import ApiError


def tryint(s):
    try:
        return int(s)
    except (TypeError, ValueError):
        return s


def alphanum_key(s):
    """Turn a string into a list of string and number chunks.
    >>> alphanum_key("z23a")
    ['z', 23, 'a']
    """
    return [tryint(c) for c in re.split("([0-9]+)", s)]


def sort_nicely(items: list) -> None:
    """
    Sort the given list in the way that humans expect.

    Example:
    >>> lst = ["1", "10", "2", "20.5", "20", "3", "30"]
    >>> sort_nicely(lst)
    >>> lst == ["1", "2", "3", "10", "20", "20.5", "30"]
    True
    """
    items.sort(key=alphanum_key)


def is_image(file: str) -> bool:
    _, ext = os.path.splitext(file)
    return ext in [".jpg", ".jpeg", ".png", ".webp"]


def make_cbz(output_dir: str):
    shutil.make_archive(output_dir, "zip", output_dir)
    shutil.move(output_dir + ".zip", output_dir + ".cbz")
    shutil.rmtree(output_dir)


DROPBOX_KOBO_ROOT = "/Aplicaciones/Rakuten Kobo"


def _dropbox_client() -> dropbox.Dropbox:
    return dropbox.Dropbox(
        app_key=os.getenv("DROPBOX_APP_KEY"),
        app_secret=os.getenv("DROPBOX_APP_SECRET"),
        oauth2_refresh_token=os.getenv("DROPBOX_REFRESH_TOKEN"),
    )


def dropbox_remote_path_for_series_cbz(
    query_path: str,
    filename_override: str | None = None,
) -> str:
    """Full Dropbox path for a series CBZ (same layout as ``upload_to_dropbox``)."""
    directory = os.path.split(os.path.dirname(query_path))[1]
    filename = filename_override or os.path.basename(query_path)
    return f"{DROPBOX_KOBO_ROOT}/{directory}/{filename}"


def dropbox_download_name_for_series_cbz(
    rel_path: str,
    filename: str | None = None,
) -> str:
    """Filename on Dropbox for this series CBZ (matches ``convert_cbz`` naming)."""
    path = rel_path.replace("\\", "/")
    fn = filename or os.path.basename(path)
    parent_dir = os.path.basename(os.path.dirname(path))
    basename, ext = os.path.splitext(fn)
    download_name = basename
    if parent_dir not in basename:
        download_name = f"{parent_dir} - {basename}"
    return download_name + ext


def upload_to_dropbox(path: str, query_path: str, filename_override: str = None):
    remote = dropbox_remote_path_for_series_cbz(query_path, filename_override)

    with open(path, "rb") as f:
        dbx = _dropbox_client()
        dbx.files_upload(
            f.read(),
            remote,
            mode=dropbox.files.WriteMode.overwrite,
        )


def delete_dropbox_path(remote_path: str) -> bool:
    """Delete file at *remote_path*. Returns False if path already absent.

    Raises on non-404 API errors.
    """
    dbx = _dropbox_client()
    try:
        dbx.files_delete_v2(remote_path)
    except ApiError as exc:
        err = exc.error
        if getattr(err, "is_path_lookup", lambda: False)():
            lookup = err.get_path_lookup()
            if getattr(lookup, "is_not_found", lambda: False)():
                return False
        raise
    return True


def get_dropbox_space_bytes() -> tuple[int, int | None]:
    """Return ``(used_bytes, allocated_bytes)``. *allocated_bytes* ``None`` if quota unknown."""
    dbx = _dropbox_client()
    usage = dbx.users_get_space_usage()
    used = int(usage.used)
    alloc = usage.allocation
    if alloc.is_individual():
        return used, int(alloc.get_individual().allocated)
    if alloc.is_team():
        team = alloc.get_team()
        per_user = int(team.user_within_team_space_allocated)
        if per_user > 0:
            return used, per_user
        return used, int(team.allocated)
    return used, None


def list_dropbox_files(path: str) -> list[dropbox.files.Metadata]:
    dbx = _dropbox_client()

    print(f"{DROPBOX_KOBO_ROOT}/{path}")

    try:
        entries: list[dropbox.files.Metadata] = []
        result = dbx.files_list_folder(f"{DROPBOX_KOBO_ROOT}/{path}")
        entries.extend(result.entries)
        while result.has_more:
            result = dbx.files_list_folder_continue(result.cursor)
            entries.extend(result.entries)
    except Exception:
        return []

    return entries
