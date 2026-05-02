import os
import re
import shutil

import dropbox


def tryint(s):
    try:
        return int(s)
    except:
        return s


def alphanum_key(s):
    """Turn a string into a list of string and number chunks.
    >>> alphanum_key("z23a")
    ['z', 23, 'a']
    """
    return [tryint(c) for c in re.split("([0-9]+)", s)]


def sort_nicely(l):
    """
    Sort the given list in the way that humans expect.

    Example:
    >>> l = ["1", "10", "2", "20.5", "20", "3", "30"]
    >>> sort_nicely(l)
    >>> l == ["1", "2", "3", "10", "20", "20.5", "30"]
    True
    """
    l.sort(key=alphanum_key)


def is_image(file: str) -> bool:
    _, ext = os.path.splitext(file)
    return ext in [".jpg", ".jpeg", ".png", ".webp"]


def make_cbz(output_dir: str):
    shutil.make_archive(output_dir, "zip", output_dir)
    shutil.move(output_dir + ".zip", output_dir + ".cbz")
    shutil.rmtree(output_dir)


def upload_to_dropbox(path: str, query_path: str, filename_override: str = None):
    directory = os.path.split(os.path.dirname(query_path))[1]
    filename = filename_override or os.path.basename(query_path)

    with open(path, "rb") as f:
        dbx = dropbox.Dropbox(
            app_key=os.getenv("DROPBOX_APP_KEY"),
            app_secret=os.getenv("DROPBOX_APP_SECRET"),
            oauth2_refresh_token=os.getenv("DROPBOX_REFRESH_TOKEN"),
        )

        dbx.files_upload(
            f.read(),
            f"/Aplicaciones/Rakuten Kobo/{directory}/{filename}",
            mode=dropbox.files.WriteMode.overwrite,
        )


def list_dropbox_files(path: str) -> list[dropbox.files.Metadata]:
    dbx = dropbox.Dropbox(
        app_key=os.getenv("DROPBOX_APP_KEY"),
        app_secret=os.getenv("DROPBOX_APP_SECRET"),
        oauth2_refresh_token=os.getenv("DROPBOX_REFRESH_TOKEN"),
    )

    print(f"/Aplicaciones/Rakuten Kobo/{path}")

    try:
        entries: list[dropbox.files.Metadata] = []
        result = dbx.files_list_folder(f"/Aplicaciones/Rakuten Kobo/{path}")
        entries.extend(result.entries)
        while result.has_more:
            result = dbx.files_list_folder_continue(result.cursor)
            entries.extend(result.entries)
    except:
        return []

    return entries
