"""Isolation of manga/manhwa conversion work directories."""

from pathlib import Path

import pytest

import manga.services as manga_services
from manga.models import MangaLibrary, Series, SeriesItem
from manga.services import convert_cbz


@pytest.mark.django_db
def test_convert_cbz_removes_temp_work_dir_after_success(tmp_path, monkeypatch):
    root = tmp_path / "m"
    root.mkdir()
    cbz = root / "series" / "ch.cbz"
    cbz.parent.mkdir(parents=True)
    cbz.write_bytes(b"PK\x03\x04")
    abs_root = str(root.resolve())
    lib = MangaLibrary.objects.create(name="m", filesystem_path=abs_root)
    s = Series.objects.create(library=lib, library_root=abs_root, series_rel_path="series", name="series")
    row = SeriesItem.objects.create(
        series=s,
        rel_path="series/ch.cbz",
        filename="ch.cbz",
        size_bytes=4,
    )

    work_dirs: list[str] = []

    def fake_process_manga(paths: list[str], work_dir: str) -> str:
        work_dirs.append(work_dir)
        out = Path(work_dir) / "output.cbz"
        out.write_bytes(b"x")
        return str(out)

    monkeypatch.setattr(manga_services, "process_manga", fake_process_manga)
    monkeypatch.setattr(manga_services, "upload_to_dropbox", lambda *_a, **_k: None)
    monkeypatch.setattr(manga_services, "get_dropbox_space_bytes", lambda: (0, 10**12))

    convert_cbz(library_id=lib.pk, item_id=row.pk, kind="manga")

    assert len(work_dirs) == 1
    assert not Path(work_dirs[0]).exists()
