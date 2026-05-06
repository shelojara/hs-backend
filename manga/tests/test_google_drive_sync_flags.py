"""Library sync refreshes ``SeriesItem.is_backed_up`` from Drive (Dropbox-style)."""

import pytest

import manga.services as manga_services
from manga.models import MangaLibrary, SeriesItem
from manga.services import sync_manga_library_cache, sync_series_items_for_cbz_path


@pytest.mark.django_db
def test_sync_series_items_sets_is_backed_up_when_filename_in_drive(tmp_path, monkeypatch):
    root = tmp_path / "lib"
    root.mkdir()
    (root / "MySeries").mkdir()
    (root / "MySeries" / "ch.cbz").write_bytes(b"x")
    monkeypatch.setattr(manga_services, "list_dropbox_files", lambda _seg: [])

    monkeypatch.setattr(
        manga_services,
        "get_series_drive_folder_id_optional",
        lambda **_: "folder1",
    )
    monkeypatch.setattr(
        manga_services,
        "list_drive_file_names_in_folder",
        lambda **_: frozenset({"ch.cbz"}),
    )

    lib = MangaLibrary.objects.create(name="lib", filesystem_path=str(root.resolve()))
    sync_series_items_for_cbz_path(library_id=lib.pk, cbz_rel_path="MySeries/ch.cbz")
    row = SeriesItem.objects.get(series__series_rel_path="MySeries", rel_path="MySeries/ch.cbz")
    assert row.is_backed_up is True


@pytest.mark.django_db
def test_sync_series_items_clears_is_backed_up_when_not_in_drive(tmp_path, monkeypatch):
    root = tmp_path / "lib"
    root.mkdir()
    (root / "MySeries").mkdir()
    (root / "MySeries" / "ch.cbz").write_bytes(b"x")
    monkeypatch.setattr(manga_services, "list_dropbox_files", lambda _seg: [])

    monkeypatch.setattr(
        manga_services,
        "get_series_drive_folder_id_optional",
        lambda **_: "folder1",
    )
    monkeypatch.setattr(
        manga_services,
        "list_drive_file_names_in_folder",
        lambda **_: frozenset({"other.cbz"}),
    )

    lib = MangaLibrary.objects.create(name="lib", filesystem_path=str(root.resolve()))
    sync_series_items_for_cbz_path(library_id=lib.pk, cbz_rel_path="MySeries/ch.cbz")
    row = SeriesItem.objects.get(series__series_rel_path="MySeries", rel_path="MySeries/ch.cbz")
    SeriesItem.objects.filter(pk=row.pk).update(is_backed_up=True)
    sync_series_items_for_cbz_path(library_id=lib.pk, cbz_rel_path="MySeries/ch.cbz")
    row.refresh_from_db()
    assert row.is_backed_up is False


@pytest.mark.django_db
def test_sync_series_items_clears_is_backed_up_when_no_drive_series_folder(tmp_path, monkeypatch):
    root = tmp_path / "lib"
    root.mkdir()
    (root / "MySeries").mkdir()
    (root / "MySeries" / "ch.cbz").write_bytes(b"x")
    monkeypatch.setattr(manga_services, "list_dropbox_files", lambda _seg: [])

    monkeypatch.setattr(
        manga_services,
        "get_series_drive_folder_id_optional",
        lambda **_: None,
    )
    called = {"n": 0}

    def _no_list(**_kwargs):
        called["n"] += 1
        return frozenset()

    monkeypatch.setattr(manga_services, "list_drive_file_names_in_folder", _no_list)

    lib = MangaLibrary.objects.create(name="lib", filesystem_path=str(root.resolve()))
    sync_series_items_for_cbz_path(library_id=lib.pk, cbz_rel_path="MySeries/ch.cbz")
    row = SeriesItem.objects.get(series__series_rel_path="MySeries", rel_path="MySeries/ch.cbz")
    SeriesItem.objects.filter(pk=row.pk).update(is_backed_up=True)
    sync_series_items_for_cbz_path(library_id=lib.pk, cbz_rel_path="MySeries/ch.cbz")
    row.refresh_from_db()
    assert row.is_backed_up is False
    assert called["n"] == 0


@pytest.mark.django_db
def test_sync_manga_library_cache_refreshes_drive_flags(tmp_path, monkeypatch):
    root = tmp_path / "lib"
    root.mkdir()
    (root / "S").mkdir()
    (root / "S" / "a.cbz").write_bytes(b"x")
    monkeypatch.setattr(manga_services, "list_dropbox_files", lambda _seg: [])

    monkeypatch.setattr(
        manga_services,
        "get_series_drive_folder_id_optional",
        lambda **_: "fid",
    )
    monkeypatch.setattr(
        manga_services,
        "list_drive_file_names_in_folder",
        lambda **_: frozenset({"a.cbz"}),
    )

    lib = MangaLibrary.objects.create(name="lib", filesystem_path=str(root.resolve()))
    sync_manga_library_cache(library_id=lib.pk)
    row = SeriesItem.objects.get(rel_path="S/a.cbz")
    assert row.is_backed_up is True


@pytest.mark.django_db
def test_sync_skips_drive_refresh_when_get_folder_raises(tmp_path, monkeypatch):
    root = tmp_path / "lib"
    root.mkdir()
    (root / "S").mkdir()
    (root / "S" / "a.cbz").write_bytes(b"x")
    monkeypatch.setattr(manga_services, "list_dropbox_files", lambda _seg: [])

    monkeypatch.setattr(
        manga_services,
        "get_series_drive_folder_id_optional",
        lambda **_k: (_ for _ in ()).throw(RuntimeError("no oauth")),
    )
    listed = {"n": 0}

    def _count_list(**_kwargs):
        listed["n"] += 1
        return frozenset()

    monkeypatch.setattr(manga_services, "list_drive_file_names_in_folder", _count_list)

    lib = MangaLibrary.objects.create(name="lib", filesystem_path=str(root.resolve()))
    sync_manga_library_cache(library_id=lib.pk)
    assert listed["n"] == 0
    row = SeriesItem.objects.get(rel_path="S/a.cbz")
    assert row.is_backed_up is False
