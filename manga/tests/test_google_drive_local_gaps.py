"""Drive folder filenames vs files under series directory on disk."""

from pathlib import Path

import pytest

import manga.services as manga_services
from manga.models import Series
from manga.services import list_series_google_drive_local_gaps


@pytest.mark.django_db
def test_local_gap_counts_missing_files(tmp_path, monkeypatch):
    root = Path(tmp_path / "lib")
    root.mkdir()
    abs_root = str(root.resolve())
    (root / "MySeries").mkdir()
    (root / "MySeries" / "one.cbz").write_bytes(b"x")
    s = Series.objects.create(
        library_root=abs_root,
        series_rel_path="MySeries",
        name="MySeries",
    )
    assert s.pk is not None
    monkeypatch.setattr(
        manga_services,
        "get_series_drive_folder_id_optional",
        lambda **_: "folder1",
    )
    monkeypatch.setattr(
        manga_services,
        "list_drive_file_names_in_folder",
        lambda **_: frozenset({"one.cbz", "two.cbz"}),
    )
    rows = list_series_google_drive_local_gaps(manga_root=abs_root, limit=10, offset=0)
    assert len(rows) == 1
    g = rows[0]
    assert g.google_drive_file_count == 2
    assert g.missing_local_file_count == 1
    assert g.series.pk == s.pk


@pytest.mark.django_db
def test_local_gap_zero_when_no_drive_folder(tmp_path, monkeypatch):
    root = Path(tmp_path / "lib2")
    root.mkdir()
    abs_root = str(root.resolve())
    (root / "S").mkdir()
    s = Series.objects.create(library_root=abs_root, series_rel_path="S", name="S")
    monkeypatch.setattr(
        manga_services,
        "get_series_drive_folder_id_optional",
        lambda **_: None,
    )
    rows = list_series_google_drive_local_gaps(manga_root=abs_root, limit=10, offset=0)
    assert len(rows) == 1
    g = rows[0]
    assert g.google_drive_file_count == 0
    assert g.missing_local_file_count == 0
    assert g.series.pk == s.pk
