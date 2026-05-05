"""Drive layout: library root folder parent."""

from manga.google_drive_service import _drive_parent_for_root_folder


def test_drive_parent_for_root_folder_is_my_drive_root():
    assert _drive_parent_for_root_folder() == "root"
