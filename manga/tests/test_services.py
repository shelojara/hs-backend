import pytest

import manga.services as manga_services
from manga.models import MangaHiddenDirectory, Series, SeriesItem
from manga.services import (
    convert_cbz,
    list_manga_cbz_files,
    list_series,
    list_series_items,
    resolve_cbz_download,
    sync_manga_library_cache,
    sync_series_items_for_cbz_path,
)


@pytest.mark.django_db
def test_sync_series_items_for_cbz_path_updates_dropbox_flags(tmp_path, monkeypatch):
    root = tmp_path / "lib"
    root.mkdir()
    (root / "MySeries").mkdir()
    (root / "MySeries" / "ch.cbz").write_bytes(b"x")

    abs_root = str(root.resolve())

    class FakeDf:
        name = "ch.cbz"

    monkeypatch.setattr(manga_services, "list_dropbox_files", lambda _seg: [FakeDf()])

    sync_series_items_for_cbz_path(manga_root=str(root), cbz_rel_path="MySeries/ch.cbz")

    s = Series.objects.get(library_root=abs_root, series_rel_path="MySeries")
    row = SeriesItem.objects.get(series=s, rel_path="MySeries/ch.cbz")
    assert row.in_dropbox is True


@pytest.mark.django_db
def test_sync_series_items_for_cbz_path_skips_hidden_series(tmp_path, monkeypatch):
    root = tmp_path / "lib"
    root.mkdir()
    (root / "secret").mkdir()
    (root / "secret" / "x.cbz").write_bytes(b"x")
    MangaHiddenDirectory.objects.create(rel_path="secret")
    monkeypatch.setattr(manga_services, "list_dropbox_files", lambda _seg: [])

    sync_series_items_for_cbz_path(manga_root=str(root), cbz_rel_path="secret/x.cbz")

    assert Series.objects.count() == 0


@pytest.mark.django_db
def test_convert_cbz_calls_sync_series_items(tmp_path, monkeypatch):
    root = tmp_path / "m"
    root.mkdir()
    cbz = root / "series" / "ch.cbz"
    cbz.parent.mkdir(parents=True)
    cbz.write_bytes(b"PK\x03\x04")

    calls = []

    def capture(**kw):
        calls.append(kw)

    monkeypatch.setattr(manga_services, "process_manga", lambda _paths: str(cbz))
    monkeypatch.setattr(manga_services, "upload_to_dropbox", lambda *_a, **_k: None)
    monkeypatch.setattr(manga_services, "sync_series_items_for_cbz_path", capture)

    convert_cbz(manga_root=str(root), path="series/ch.cbz", kind="manga")
    assert calls == [{"manga_root": str(root), "cbz_rel_path": "series/ch.cbz"}]


def test_resolve_cbz_download_ok(tmp_path):
    root = tmp_path / "m"
    cbz = root / "s" / "ch.cbz"
    cbz.parent.mkdir(parents=True)
    cbz.write_bytes(b"x")

    got = resolve_cbz_download(manga_root=str(root), path="s/ch.cbz")
    assert got.absolute_path == str(cbz)
    assert got.filename == "ch.cbz"


def test_resolve_cbz_download_rejects_non_cbz(tmp_path):
    root = tmp_path / "m"
    root.mkdir()
    with pytest.raises(ValueError, match="Not a CBZ"):
        resolve_cbz_download(manga_root=str(root), path="x.zip")


def test_resolve_cbz_download_rejects_path_escape(tmp_path):
    root = tmp_path / "m"
    root.mkdir()
    with pytest.raises(ValueError, match="outside manga root"):
        resolve_cbz_download(manga_root=str(root), path="../outside.cbz")


def test_resolve_cbz_download_missing_file(tmp_path):
    root = tmp_path / "m"
    root.mkdir()
    with pytest.raises(ValueError, match="CBZ not found"):
        resolve_cbz_download(manga_root=str(root), path="missing.cbz")


@pytest.mark.django_db
def test_list_manga_cbz_files_missing_root_returns_empty(tmp_path):
    missing = tmp_path / "no_manga"
    assert list_manga_cbz_files(manga_root=str(missing), path="") == []


@pytest.mark.django_db
def test_list_manga_cbz_files_shallow_only_cbz(tmp_path, monkeypatch):
    root = tmp_path / "manga"
    (root / "a").mkdir(parents=True)
    (root / "b" / "nested").mkdir(parents=True)
    (root / "a" / "1.cbz").write_bytes(b"x")
    (root / "b" / "nested" / "2.cbz").write_bytes(b"yy")
    (root / "root.cbz").write_bytes(b"r")
    (root / "readme.txt").write_text("nope", encoding="utf-8")
    (root / "b" / "archive.zip").write_bytes(b"z")
    monkeypatch.setattr(manga_services, "list_dropbox_files", lambda _path: [])

    got = list_manga_cbz_files(manga_root=str(root), path="")
    assert len(got) == 1
    assert got[0].path.replace("\\", "/") == "root.cbz"
    assert got[0].size == 1

    nested_only = list_manga_cbz_files(manga_root=str(root), path="b/nested")
    assert [i.path.replace("\\", "/") for i in nested_only] == ["b/nested/2.cbz"]


@pytest.mark.django_db
def test_list_manga_cbz_files_uppercase_ext(tmp_path, monkeypatch):
    root = tmp_path / "m"
    root.mkdir()
    (root / "X.CBZ").write_bytes(b"")
    monkeypatch.setattr(manga_services, "list_dropbox_files", lambda _path: [])

    got = list_manga_cbz_files(manga_root=str(root), path="")
    assert len(got) == 1
    assert got[0].name == "X.CBZ"


@pytest.mark.django_db
def test_list_manga_cbz_files_respects_hidden_directories(tmp_path, monkeypatch):
    root = tmp_path / "manga"
    root.mkdir()
    (root / "visible").mkdir()
    (root / "hide_me").mkdir()
    (root / "visible" / "ok.cbz").write_bytes(b"")
    (root / "hide_me" / "secret.cbz").write_bytes(b"")
    MangaHiddenDirectory.objects.create(rel_path="hide_me")
    monkeypatch.setattr(manga_services, "list_dropbox_files", lambda _path: [])

    got = list_manga_cbz_files(manga_root=str(root), path="visible")
    assert [i.path.replace("\\", "/") for i in got] == ["visible/ok.cbz"]

    assert list_manga_cbz_files(manga_root=str(root), path="hide_me") == []


@pytest.mark.django_db
def test_list_manga_cbz_files_scoped_to_path(tmp_path, monkeypatch):
    root = tmp_path / "manga"
    (root / "a").mkdir(parents=True)
    (root / "b" / "nested").mkdir(parents=True)
    (root / "a" / "1.cbz").write_bytes(b"x")
    (root / "b" / "nested" / "2.cbz").write_bytes(b"yy")
    monkeypatch.setattr(manga_services, "list_dropbox_files", lambda _path: [])

    only_a = list_manga_cbz_files(manga_root=str(root), path="a")
    assert [i.path.replace("\\", "/") for i in only_a] == ["a/1.cbz"]

    only_b = list_manga_cbz_files(manga_root=str(root), path="b")
    assert only_b == []


@pytest.mark.django_db
def test_list_manga_cbz_files_file_path_raises(tmp_path):
    root = tmp_path / "m"
    root.mkdir()
    (root / "sub").mkdir()
    (root / "sub" / "ch.cbz").write_bytes(b"abc")

    with pytest.raises(ValueError, match="Path must be a directory"):
        list_manga_cbz_files(manga_root=str(root), path="sub/ch.cbz")


@pytest.mark.django_db
def test_list_manga_cbz_files_non_cbz_file_path_raises(tmp_path):
    root = tmp_path / "m"
    root.mkdir()
    (root / "x.txt").write_text("n", encoding="utf-8")

    with pytest.raises(ValueError, match="Path must be a directory"):
        list_manga_cbz_files(manga_root=str(root), path="x.txt")


@pytest.mark.django_db
def test_list_manga_cbz_files_missing_subpath_returns_empty(tmp_path, monkeypatch):
    root = tmp_path / "m"
    root.mkdir()
    monkeypatch.setattr(manga_services, "list_dropbox_files", lambda _path: [])

    assert list_manga_cbz_files(manga_root=str(root), path="no_such_dir") == []


@pytest.mark.django_db
def test_sync_manga_library_cache_series_is_dir_with_direct_cbz(tmp_path, monkeypatch):
    root = tmp_path / "lib"
    root.mkdir()
    (root / "Alpha").mkdir()
    (root / "Alpha" / "c1.cbz").write_bytes(b"x")
    (root / "nested").mkdir()
    (root / "nested" / "deep.cbz").write_bytes(b"y")
    monkeypatch.setattr(manga_services, "list_dropbox_files", lambda _path: [])

    n_series, n_ch = sync_manga_library_cache(manga_root=str(root))
    assert n_series == 2
    assert n_ch == 2

    abs_root = str(root.resolve())
    s_alpha = Series.objects.get(library_root=abs_root, series_rel_path="Alpha")
    assert s_alpha.name == "Alpha"
    assert SeriesItem.objects.filter(series=s_alpha).count() == 1

    s_nested = Series.objects.get(library_root=abs_root, series_rel_path="nested")
    assert s_nested.name == "nested"

    listed = list_series(manga_root=str(root))
    assert [r.series_rel_path for r in listed] == ["Alpha", "nested"]
    assert [r.name for r in listed] == ["Alpha", "nested"]

    paged = list_series(manga_root=str(root), limit=1, offset=1)
    assert len(paged) == 1
    assert paged[0].series_rel_path == "nested"
    assert paged[0].name == "nested"

    items = list_series_items(manga_root=str(root), series_id=s_alpha.id)
    assert len(items) == 1
    assert items[0].rel_path == "Alpha/c1.cbz"
    assert items[0].filename == "c1.cbz"


@pytest.mark.django_db
def test_list_series_items_unknown_series_raises(tmp_path):
    root = tmp_path / "lib"
    root.mkdir()
    with pytest.raises(ValueError, match="Series not found"):
        list_series_items(manga_root=str(root), series_id=999)


@pytest.mark.django_db
def test_list_series_orders_by_name_not_series_rel_path(tmp_path, monkeypatch):
    root = tmp_path / "lib"
    root.mkdir()
    (root / "zzz" / "nested").mkdir(parents=True)
    (root / "zzz" / "nested" / "a.cbz").write_bytes(b"x")
    (root / "aaa" / "top").mkdir(parents=True)
    (root / "aaa" / "top" / "b.cbz").write_bytes(b"y")
    monkeypatch.setattr(manga_services, "list_dropbox_files", lambda _path: [])

    sync_manga_library_cache(manga_root=str(root))
    listed = list_series(manga_root=str(root))
    assert [r.name for r in listed] == ["nested", "top"]
    assert [r.series_rel_path for r in listed] == ["zzz/nested", "aaa/top"]

    paged = list_series(manga_root=str(root), limit=1, offset=1)
    assert paged[0].name == "top"
    assert paged[0].series_rel_path == "aaa/top"


@pytest.mark.django_db
def test_sync_manga_library_cache_skips_hidden_series_dirs(tmp_path, monkeypatch):
    root = tmp_path / "lib"
    root.mkdir()
    (root / "gone").mkdir()
    (root / "gone" / "x.cbz").write_bytes(b"x")
    MangaHiddenDirectory.objects.create(rel_path="gone")
    monkeypatch.setattr(manga_services, "list_dropbox_files", lambda _path: [])

    sync_manga_library_cache(manga_root=str(root))
    assert Series.objects.filter(series_rel_path="gone").count() == 0


@pytest.mark.django_db
def test_convert_cbz_rejects_path_escape(tmp_path, monkeypatch):
    root = tmp_path / "m"
    root.mkdir()
    monkeypatch.setattr(manga_services, "process_manga", lambda _paths: (_ for _ in ()).throw(AssertionError))

    with pytest.raises(ValueError, match="outside manga root"):
        convert_cbz(manga_root=str(root), path="../evil.cbz", kind="manga")
