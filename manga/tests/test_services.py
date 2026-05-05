import base64
import os
import shutil
import zipfile
from io import BytesIO

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from PIL import Image

import manga.services as manga_services
from manga.models import (
    CbzConvertJob,
    MangaHiddenDirectory,
    Series,
    SeriesItem,
)
from manga.services import (
    build_cbz_page_slice,
    clean_cbz_display_name,
    clean_series_item_filename_on_disk,
    convert_cbz,
    first_cbz_page_as_base64,
    list_distinct_series_categories,
    list_manga_cbz_files,
    get_series,
    list_series,
    list_series_items,
    resolve_cbz_download,
    series_is_fully_backed_up_value,
    sync_manga_library_cache,
    sync_series_items_for_cbz_path,
    sync_series_items_for_series,
)
from manga.cbztools.utils import (
    dropbox_download_name_for_series_cbz,
    dropbox_remote_path_for_series_cbz,
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
    assert s.item_count == 1
    row = SeriesItem.objects.get(series=s, rel_path="MySeries/ch.cbz")
    assert row.is_converted is True
    assert row.dropbox_uploaded_at is not None


@pytest.mark.django_db
def test_sync_series_items_sets_dropbox_uploaded_at_when_newly_seen_in_dropbox(tmp_path, monkeypatch):
    root = tmp_path / "lib"
    root.mkdir()
    (root / "MySeries").mkdir()
    (root / "MySeries" / "ch.cbz").write_bytes(b"x")
    abs_root = str(root.resolve())

    class FakeDf:
        name = "ch.cbz"

    monkeypatch.setattr(manga_services, "list_dropbox_files", lambda _seg: [FakeDf()])
    sync_series_items_for_cbz_path(manga_root=str(root), cbz_rel_path="MySeries/ch.cbz")
    row = SeriesItem.objects.get(
        series__library_root=abs_root,
        rel_path="MySeries/ch.cbz",
    )
    first = row.dropbox_uploaded_at
    assert first is not None

    SeriesItem.objects.filter(pk=row.pk).update(dropbox_uploaded_at=None)
    sync_series_items_for_cbz_path(manga_root=str(root), cbz_rel_path="MySeries/ch.cbz")
    row.refresh_from_db()
    assert row.dropbox_uploaded_at is not None
    assert row.dropbox_uploaded_at >= first


@pytest.mark.django_db
def test_sync_series_items_clears_dropbox_uploaded_at_when_not_in_dropbox(tmp_path, monkeypatch):
    root = tmp_path / "lib"
    root.mkdir()
    (root / "MySeries").mkdir()
    (root / "MySeries" / "ch.cbz").write_bytes(b"x")
    abs_root = str(root.resolve())

    class FakeDf:
        name = "ch.cbz"

    monkeypatch.setattr(manga_services, "list_dropbox_files", lambda _seg: [FakeDf()])
    sync_series_items_for_cbz_path(manga_root=str(root), cbz_rel_path="MySeries/ch.cbz")
    row = SeriesItem.objects.get(series__library_root=abs_root, rel_path="MySeries/ch.cbz")
    assert row.dropbox_uploaded_at is not None

    monkeypatch.setattr(manga_services, "list_dropbox_files", lambda _seg: [])
    sync_series_items_for_cbz_path(manga_root=str(root), cbz_rel_path="MySeries/ch.cbz")
    row.refresh_from_db()
    assert row.is_converted is False
    assert row.dropbox_uploaded_at is None


@pytest.mark.django_db
def test_sync_series_items_sets_file_created_at_from_filesystem(tmp_path, monkeypatch):
    root = tmp_path / "lib"
    root.mkdir()
    (root / "MySeries").mkdir()
    cbz = root / "MySeries" / "ch.cbz"
    cbz.write_bytes(b"x")

    monkeypatch.setattr(manga_services, "list_dropbox_files", lambda _path: [])

    sync_series_items_for_cbz_path(manga_root=str(root), cbz_rel_path="MySeries/ch.cbz")

    s = Series.objects.get(library_root=str(root.resolve()), series_rel_path="MySeries")
    row = SeriesItem.objects.get(series=s, rel_path="MySeries/ch.cbz")
    assert row.file_created_at is not None
    expected = manga_services._filesystem_created_at_from_stat(os.stat(cbz))
    assert expected is not None
    assert abs((row.file_created_at - expected).total_seconds()) < 1


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
def test_sync_series_items_for_series_upserts_from_disk(tmp_path, monkeypatch):
    root = tmp_path / "lib"
    root.mkdir()
    (root / "MySeries").mkdir()
    (root / "MySeries" / "a.cbz").write_bytes(b"x")
    (root / "MySeries" / "b.cbz").write_bytes(b"y")
    abs_root = str(root.resolve())
    s = Series.objects.create(library_root=abs_root, series_rel_path="MySeries", name="MySeries")
    SeriesItem.objects.create(
        series=s,
        rel_path="MySeries/a.cbz",
        filename="a.cbz",
        size_bytes=1,
    )
    monkeypatch.setattr(manga_services, "list_dropbox_files", lambda _seg: [])

    out = sync_series_items_for_series(manga_root=str(root), series_id=s.pk)

    assert out.pk == s.pk
    assert out.item_count == 2
    rels = set(SeriesItem.objects.filter(series_id=s.pk).values_list("rel_path", flat=True))
    assert rels == {"MySeries/a.cbz", "MySeries/b.cbz"}


@pytest.mark.django_db
def test_sync_series_items_for_series_raises_when_hidden(tmp_path, monkeypatch):
    root = tmp_path / "lib"
    root.mkdir()
    (root / "secret").mkdir()
    (root / "secret" / "x.cbz").write_bytes(b"x")
    abs_root = str(root.resolve())
    s = Series.objects.create(library_root=abs_root, series_rel_path="secret", name="secret")
    MangaHiddenDirectory.objects.create(rel_path="secret")
    monkeypatch.setattr(manga_services, "list_dropbox_files", lambda _seg: [])

    with pytest.raises(ValueError, match="hidden"):
        sync_series_items_for_series(manga_root=str(root), series_id=s.pk)


@pytest.mark.django_db
def test_sync_series_items_for_series_raises_when_series_missing(tmp_path):
    root = tmp_path / "lib"
    root.mkdir()
    abs_root = str(root.resolve())

    with pytest.raises(ValueError, match="Series not found"):
        sync_series_items_for_series(manga_root=str(abs_root), series_id=99999)


@pytest.mark.django_db
def test_dropbox_download_name_matches_convert_cbz_layout():
    assert dropbox_download_name_for_series_cbz("MySeries/ch01.cbz") == "MySeries - ch01.cbz"
    assert dropbox_download_name_for_series_cbz("MySeries/MySeries ch01.cbz") == "MySeries ch01.cbz"


@pytest.mark.django_db
def test_convert_cbz_evicts_oldest_dropbox_first_when_full(tmp_path, monkeypatch):
    root = tmp_path / "m"
    root.mkdir()
    abs_root = str(root.resolve())
    s = Series.objects.create(library_root=abs_root, series_rel_path="series", name="series")
    old = SeriesItem.objects.create(
        series=s,
        rel_path="series/old.cbz",
        filename="old.cbz",
        size_bytes=1,
        is_converted=True,
        dropbox_uploaded_at=timezone.now(),
    )
    new = SeriesItem.objects.create(
        series=s,
        rel_path="series/new.cbz",
        filename="new.cbz",
        size_bytes=1,
    )
    cbz = root / "series" / "new.cbz"
    cbz.parent.mkdir(parents=True)
    cbz.write_bytes(b"PK\x03\x04")

    monkeypatch.setattr(manga_services, "process_manga", lambda _paths, _wd: str(cbz))
    monkeypatch.setattr(manga_services, "upload_to_dropbox", lambda *_a, **_k: None)

    space_calls: list[tuple[int, int | None]] = []

    def fake_space():
        if len(space_calls) == 0:
            space_calls.append((1000, 1000))
            return (1000, 1000)
        space_calls.append((500, 1000))
        return (500, 1000)

    deleted: list[str] = []

    def fake_delete(path: str):
        deleted.append(path)
        return True

    monkeypatch.setattr(manga_services, "get_dropbox_space_bytes", fake_space)
    monkeypatch.setattr(manga_services, "delete_dropbox_path", fake_delete)

    convert_cbz(manga_root=str(root), item_id=new.pk, kind="manga")

    old.refresh_from_db()
    new.refresh_from_db()
    assert old.is_converted is False
    assert old.dropbox_uploaded_at is None
    assert new.is_converted is True
    assert new.dropbox_uploaded_at is not None
    assert deleted == [
        dropbox_remote_path_for_series_cbz(
            old.rel_path,
            dropbox_download_name_for_series_cbz(old.rel_path, old.filename),
        ),
    ]


@pytest.mark.django_db
def test_convert_cbz_raises_when_dropbox_full_and_nothing_to_evict(tmp_path, monkeypatch):
    root = tmp_path / "m"
    root.mkdir()
    abs_root = str(root.resolve())
    s = Series.objects.create(library_root=abs_root, series_rel_path="series", name="series")
    row = SeriesItem.objects.create(
        series=s,
        rel_path="series/only.cbz",
        filename="only.cbz",
        size_bytes=1,
    )
    cbz = root / "series" / "only.cbz"
    cbz.parent.mkdir(parents=True)
    cbz.write_bytes(b"PK\x03\x04")

    monkeypatch.setattr(manga_services, "process_manga", lambda _paths, _wd: str(cbz))
    monkeypatch.setattr(manga_services, "upload_to_dropbox", lambda *_a, **_k: None)
    monkeypatch.setattr(manga_services, "get_dropbox_space_bytes", lambda: (1000, 1000))

    with pytest.raises(RuntimeError, match="no eligible"):
        convert_cbz(manga_root=str(root), item_id=row.pk, kind="manga")


@pytest.mark.django_db
def test_convert_cbz_sets_dropbox_fields_without_series_resync(tmp_path, monkeypatch):
    root = tmp_path / "m"
    root.mkdir()
    cbz = root / "series" / "ch.cbz"
    cbz.parent.mkdir(parents=True)
    cbz.write_bytes(b"PK\x03\x04")
    abs_root = str(root.resolve())
    s = Series.objects.create(library_root=abs_root, series_rel_path="series", name="series")
    row = SeriesItem.objects.create(
        series=s,
        rel_path="series/ch.cbz",
        filename="ch.cbz",
        size_bytes=4,
    )

    monkeypatch.setattr(manga_services, "process_manga", lambda _paths, _wd: str(cbz))
    monkeypatch.setattr(manga_services, "upload_to_dropbox", lambda *_a, **_k: None)
    monkeypatch.setattr(manga_services, "get_dropbox_space_bytes", lambda: (0, 10**12))

    convert_cbz(manga_root=str(root), item_id=row.pk, kind="manga")
    row.refresh_from_db()
    assert row.is_converted is True
    assert row.dropbox_uploaded_at is not None


@pytest.mark.django_db
def test_resolve_cbz_download_ok(tmp_path):
    root = tmp_path / "m"
    cbz = root / "s" / "ch.cbz"
    cbz.parent.mkdir(parents=True)
    cbz.write_bytes(b"x")
    abs_root = str(root.resolve())
    s = Series.objects.create(library_root=abs_root, series_rel_path="s", name="s")
    row = SeriesItem.objects.create(series=s, rel_path="s/ch.cbz", filename="ch.cbz", size_bytes=1)

    got = resolve_cbz_download(manga_root=str(root), item_id=row.pk)
    assert got.absolute_path == str(cbz)
    assert got.filename == "ch.cbz"


@pytest.mark.django_db
def test_resolve_cbz_download_rejects_non_cbz(tmp_path):
    root = tmp_path / "m"
    root.mkdir()
    z = root / "x.zip"
    z.write_bytes(b"z")
    abs_root = str(root.resolve())
    s = Series.objects.create(library_root=abs_root, series_rel_path="", name="lib")
    row = SeriesItem.objects.create(series=s, rel_path="x.zip", filename="x.zip", size_bytes=1)
    with pytest.raises(ValueError, match="Not a CBZ"):
        resolve_cbz_download(manga_root=str(root), item_id=row.pk)


@pytest.mark.django_db
def test_resolve_cbz_download_rejects_item_wrong_library(tmp_path):
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    root_a.mkdir()
    root_b.mkdir()
    abs_a = str(root_a.resolve())
    abs_b = str(root_b.resolve())
    s = Series.objects.create(library_root=abs_a, series_rel_path="s", name="s")
    row = SeriesItem.objects.create(series=s, rel_path="s/ch.cbz", filename="ch.cbz", size_bytes=0)
    with pytest.raises(ValueError, match="Item not found"):
        resolve_cbz_download(manga_root=abs_b, item_id=row.pk)


@pytest.mark.django_db
def test_resolve_cbz_download_missing_file(tmp_path):
    root = tmp_path / "m"
    root.mkdir()
    abs_root = str(root.resolve())
    s = Series.objects.create(library_root=abs_root, series_rel_path="s", name="s")
    row = SeriesItem.objects.create(series=s, rel_path="s/missing.cbz", filename="missing.cbz", size_bytes=0)
    with pytest.raises(ValueError, match="CBZ not found"):
        resolve_cbz_download(manga_root=str(root), item_id=row.pk)


def _write_minimal_cbz(path, member_names: list[str]) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        for name in member_names:
            zf.writestr(name, b"p")


def _write_cbz_member_bytes(path, members: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)


def _minimal_jpeg_bytes() -> bytes:
    buf = BytesIO()
    Image.new("RGB", (1, 1), (0, 0, 0)).save(buf, format="JPEG")
    return buf.getvalue()


@pytest.mark.django_db
def test_build_cbz_page_slice_returns_slice_sorted_natural(tmp_path):
    root = tmp_path / "m"
    cbz = root / "s" / "ch.cbz"
    cbz.parent.mkdir(parents=True)
    _write_minimal_cbz(
        cbz,
        ["010.jpg", "002.jpg", "001.jpg"],
    )
    abs_root = str(root.resolve())
    s = Series.objects.create(library_root=abs_root, series_rel_path="s", name="s")
    row = SeriesItem.objects.create(series=s, rel_path="s/ch.cbz", filename="ch.cbz", size_bytes=1)

    built = build_cbz_page_slice(manga_root=str(root), item_id=row.pk, offset=0, limit=2)
    assert built.filename == "ch_m0-1.cbz"
    with zipfile.ZipFile(built.content, "r") as zf:
        assert zf.namelist() == ["001.jpg", "002.jpg"]
    built.content.close()


@pytest.mark.django_db
def test_build_cbz_page_slice_second_page_window(tmp_path):
    root = tmp_path / "m"
    cbz = root / "s" / "ch.cbz"
    cbz.parent.mkdir(parents=True)
    _write_minimal_cbz(cbz, ["a.jpg", "b.jpg", "c.jpg"])
    abs_root = str(root.resolve())
    s = Series.objects.create(library_root=abs_root, series_rel_path="s", name="s")
    row = SeriesItem.objects.create(series=s, rel_path="s/ch.cbz", filename="ch.cbz", size_bytes=1)

    built = build_cbz_page_slice(manga_root=str(root), item_id=row.pk, offset=1, limit=2)
    assert built.filename == "ch_m1-2.cbz"
    with zipfile.ZipFile(built.content, "r") as zf:
        assert zf.namelist() == ["b.jpg", "c.jpg"]
    built.content.close()


@pytest.mark.django_db
def test_build_cbz_page_slice_offset_out_of_range(tmp_path):
    root = tmp_path / "m"
    cbz = root / "s" / "ch.cbz"
    cbz.parent.mkdir(parents=True)
    _write_minimal_cbz(cbz, ["a.jpg"])
    abs_root = str(root.resolve())
    s = Series.objects.create(library_root=abs_root, series_rel_path="s", name="s")
    row = SeriesItem.objects.create(series=s, rel_path="s/ch.cbz", filename="ch.cbz", size_bytes=1)

    with pytest.raises(ValueError, match="Offset out of range"):
        build_cbz_page_slice(manga_root=str(root), item_id=row.pk, offset=1, limit=5)


@pytest.mark.django_db
def test_build_cbz_page_slice_no_images(tmp_path):
    root = tmp_path / "m"
    cbz = root / "s" / "ch.cbz"
    cbz.parent.mkdir(parents=True)
    _write_minimal_cbz(cbz, ["readme.txt"])
    abs_root = str(root.resolve())
    s = Series.objects.create(library_root=abs_root, series_rel_path="s", name="s")
    row = SeriesItem.objects.create(series=s, rel_path="s/ch.cbz", filename="ch.cbz", size_bytes=1)

    with pytest.raises(ValueError, match="No image pages in CBZ"):
        build_cbz_page_slice(manga_root=str(root), item_id=row.pk, offset=0, limit=10)


@pytest.mark.django_db
def test_build_cbz_page_slice_invalid_zip(tmp_path):
    root = tmp_path / "m"
    cbz = root / "s" / "ch.cbz"
    cbz.parent.mkdir(parents=True)
    cbz.write_bytes(b"not a zip")
    abs_root = str(root.resolve())
    s = Series.objects.create(library_root=abs_root, series_rel_path="s", name="s")
    row = SeriesItem.objects.create(series=s, rel_path="s/ch.cbz", filename="ch.cbz", size_bytes=1)

    with pytest.raises(ValueError, match="Invalid CBZ file"):
        build_cbz_page_slice(manga_root=str(root), item_id=row.pk, offset=0, limit=1)


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
    assert s_alpha.item_count == 1
    assert SeriesItem.objects.filter(series=s_alpha).count() == 1

    s_nested = Series.objects.get(library_root=abs_root, series_rel_path="nested")
    assert s_nested.name == "nested"
    assert s_nested.item_count == 1

    listed = list_series(manga_root=str(root))
    assert [r.series_rel_path for r in listed] == ["Alpha", "nested"]
    assert [r.name for r in listed] == ["Alpha", "nested"]

    paged = list_series(manga_root=str(root), limit=1, offset=1)
    assert len(paged) == 1
    assert paged[0].series_rel_path == "nested"
    assert paged[0].name == "nested"

    items = list_series_items(manga_root=str(root), series_id=s_alpha.id)
    assert len(items) == 1
    assert items[0].filename == "c1.cbz"

    assert s_alpha.category == ""
    assert s_nested.category == ""


@pytest.mark.django_db
def test_series_category_parent_directory_basename(tmp_path, monkeypatch):
    root = tmp_path / "lib"
    root.mkdir()
    (root / "TopOnly").mkdir()
    (root / "TopOnly" / "a.cbz").write_bytes(b"x")
    (root / "Shonen" / "Naruto").mkdir(parents=True)
    (root / "Shonen" / "Naruto" / "ch.cbz").write_bytes(b"x")
    (root / "root.cbz").write_bytes(b"z")
    monkeypatch.setattr(manga_services, "list_dropbox_files", lambda _path: [])

    sync_manga_library_cache(manga_root=str(root))
    abs_root = str(root.resolve())

    top = Series.objects.get(library_root=abs_root, series_rel_path="TopOnly")
    assert top.category == ""

    nested = Series.objects.get(library_root=abs_root, series_rel_path="Shonen/Naruto")
    assert nested.category == "Shonen"

    at_lib_root = Series.objects.get(library_root=abs_root, series_rel_path="")
    assert at_lib_root.category == ""


@pytest.mark.django_db
def test_list_series_filters_by_category(tmp_path, monkeypatch):
    root = tmp_path / "lib"
    root.mkdir()
    (root / "Shonen" / "A").mkdir(parents=True)
    (root / "Shonen" / "A" / "a.cbz").write_bytes(b"x")
    (root / "Shonen" / "B").mkdir(parents=True)
    (root / "Shonen" / "B" / "b.cbz").write_bytes(b"y")
    (root / "Seinen" / "C").mkdir(parents=True)
    (root / "Seinen" / "C" / "c.cbz").write_bytes(b"z")
    (root / "root.cbz").write_bytes(b"w")
    monkeypatch.setattr(manga_services, "list_dropbox_files", lambda _path: [])

    sync_manga_library_cache(manga_root=str(root))

    shonen = list_series(manga_root=str(root), category="Shonen")
    assert {r.series_rel_path for r in shonen} == {"Shonen/A", "Shonen/B"}

    shonen_stripped = list_series(manga_root=str(root), category="  Shonen  ")
    assert {r.series_rel_path for r in shonen_stripped} == {"Shonen/A", "Shonen/B"}

    seinen = list_series(manga_root=str(root), category="Seinen")
    assert [r.series_rel_path for r in seinen] == ["Seinen/C"]

    all_rows = list_series(manga_root=str(root))
    assert len(all_rows) == 4


@pytest.mark.django_db
def test_list_distinct_series_categories(tmp_path, monkeypatch):
    root = tmp_path / "lib"
    root.mkdir()
    (root / "Shonen" / "A").mkdir(parents=True)
    (root / "Shonen" / "A" / "a.cbz").write_bytes(b"x")
    (root / "Shonen" / "B").mkdir(parents=True)
    (root / "Shonen" / "B" / "b.cbz").write_bytes(b"y")
    (root / "Seinen" / "C").mkdir(parents=True)
    (root / "Seinen" / "C" / "c.cbz").write_bytes(b"z")
    (root / "root.cbz").write_bytes(b"w")
    monkeypatch.setattr(manga_services, "list_dropbox_files", lambda _path: [])

    sync_manga_library_cache(manga_root=str(root))

    assert list_distinct_series_categories(manga_root=str(root)) == ["Seinen", "Shonen"]


@pytest.mark.django_db
def test_list_series_rejects_empty_category_filter(tmp_path, monkeypatch):
    root = tmp_path / "lib"
    root.mkdir()
    (root / "S").mkdir()
    (root / "S" / "a.cbz").write_bytes(b"x")
    monkeypatch.setattr(manga_services, "list_dropbox_files", lambda _path: [])

    sync_manga_library_cache(manga_root=str(root))

    with pytest.raises(ValueError, match="non-empty"):
        list_series(manga_root=str(root), category="")
    with pytest.raises(ValueError, match="non-empty"):
        list_series(manga_root=str(root), category="   ")


@pytest.mark.django_db
def test_list_series_filters_by_search(tmp_path, monkeypatch):
    root = tmp_path / "lib"
    root.mkdir()
    (root / "Shonen" / "Naruto").mkdir(parents=True)
    (root / "Shonen" / "Naruto" / "a.cbz").write_bytes(b"x")
    (root / "Seinen" / "Berserk").mkdir(parents=True)
    (root / "Seinen" / "Berserk" / "b.cbz").write_bytes(b"y")
    monkeypatch.setattr(manga_services, "list_dropbox_files", lambda _path: [])

    sync_manga_library_cache(manga_root=str(root))

    by_name = list_series(manga_root=str(root), search="naruto")
    assert [r.series_rel_path for r in by_name] == ["Shonen/Naruto"]

    by_rel = list_series(manga_root=str(root), search="Seinen/Ber")
    assert [r.series_rel_path for r in by_rel] == ["Seinen/Berserk"]

    by_cat = list_series(manga_root=str(root), search="shonen")
    assert [r.series_rel_path for r in by_cat] == ["Shonen/Naruto"]

    combined = list_series(manga_root=str(root), category="Seinen", search="ser")
    assert [r.series_rel_path for r in combined] == ["Seinen/Berserk"]


@pytest.mark.django_db
def test_list_series_rejects_empty_search_filter(tmp_path, monkeypatch):
    root = tmp_path / "lib"
    root.mkdir()
    (root / "S").mkdir()
    (root / "S" / "a.cbz").write_bytes(b"x")
    monkeypatch.setattr(manga_services, "list_dropbox_files", lambda _path: [])

    sync_manga_library_cache(manga_root=str(root))

    with pytest.raises(ValueError, match="non-empty"):
        list_series(manga_root=str(root), search="")
    with pytest.raises(ValueError, match="non-empty"):
        list_series(manga_root=str(root), search="   ")


@pytest.mark.django_db
def test_sync_manga_library_cache_commits_series_before_failing_one(tmp_path, monkeypatch):
    """Per-series transactions: earlier series stay persisted when a later series raises."""
    root = tmp_path / "lib"
    root.mkdir()
    (root / "Alpha").mkdir()
    (root / "Alpha" / "c1.cbz").write_bytes(b"x")
    (root / "Beta").mkdir()
    (root / "Beta" / "c2.cbz").write_bytes(b"y")
    monkeypatch.setattr(manga_services, "list_dropbox_files", lambda _path: [])

    orig_list = manga_services.list_manga_cbz_files

    def list_cbz_fail_beta(*args, **kwargs):
        if kwargs.get("path") == "Beta":
            raise RuntimeError("simulated Beta failure")
        return orig_list(*args, **kwargs)

    monkeypatch.setattr(manga_services, "list_manga_cbz_files", list_cbz_fail_beta)

    abs_root = str(root.resolve())
    with pytest.raises(RuntimeError, match="simulated Beta"):
        sync_manga_library_cache(manga_root=str(root))

    assert Series.objects.filter(library_root=abs_root).count() == 1
    kept = Series.objects.get(library_root=abs_root)
    assert kept.series_rel_path == "Alpha"
    assert kept.item_count == 1
    assert SeriesItem.objects.filter(series=kept).count() == 1


@pytest.mark.django_db
def test_list_series_items_sorts_filenames_naturally(tmp_path, monkeypatch):
    root = tmp_path / "lib"
    root.mkdir()
    (root / "S").mkdir()
    for name in ("ch10.cbz", "ch2.cbz", "ch1.cbz"):
        (root / "S" / name).write_bytes(b"x")
    monkeypatch.setattr(manga_services, "list_dropbox_files", lambda _path: [])

    sync_manga_library_cache(manga_root=str(root))
    s = Series.objects.get(library_root=str(root.resolve()), series_rel_path="S")
    assert s.item_count == 3
    names = [r.filename for r in list_series_items(manga_root=str(root), series_id=s.id)]
    assert names == ["ch1.cbz", "ch2.cbz", "ch10.cbz"]


@pytest.mark.django_db
def test_list_series_items_filters_by_is_converted(tmp_path, monkeypatch):
    root = tmp_path / "lib"
    root.mkdir()
    (root / "S").mkdir()
    (root / "S" / "a.cbz").write_bytes(b"x")
    (root / "S" / "b.cbz").write_bytes(b"y")
    monkeypatch.setattr(manga_services, "list_dropbox_files", lambda _path: [])

    sync_manga_library_cache(manga_root=str(root))
    s = Series.objects.get(library_root=str(root.resolve()), series_rel_path="S")
    a = SeriesItem.objects.get(series=s, filename="a.cbz")
    b = SeriesItem.objects.get(series=s, filename="b.cbz")
    a.is_converted = True
    a.save(update_fields=["is_converted"])

    only_dropbox = list_series_items(
        manga_root=str(root), series_id=s.id, is_converted=True
    )
    assert [r.id for r in only_dropbox] == [a.id]

    not_dropbox = list_series_items(
        manga_root=str(root), series_id=s.id, is_converted=False
    )
    assert [r.id for r in not_dropbox] == [b.id]

    all_items = list_series_items(manga_root=str(root), series_id=s.id)
    assert {r.id for r in all_items} == {a.id, b.id}


@pytest.mark.django_db
def test_list_series_items_google_drive_backed_up_flag(tmp_path, monkeypatch):
    root = tmp_path / "lib"
    root.mkdir()
    (root / "S").mkdir()
    (root / "S" / "a.cbz").write_bytes(b"x")
    (root / "S" / "b.cbz").write_bytes(b"y")
    monkeypatch.setattr(manga_services, "list_dropbox_files", lambda _path: [])

    sync_manga_library_cache(manga_root=str(root))
    s = Series.objects.get(library_root=str(root.resolve()), series_rel_path="S")
    a = SeriesItem.objects.get(series=s, filename="a.cbz")
    b = SeriesItem.objects.get(series=s, filename="b.cbz")
    assert a.is_backed_up is False
    SeriesItem.objects.filter(pk=a.pk).update(is_backed_up=True)

    rows = list_series_items(manga_root=str(root), series_id=s.id)
    by_id = {r.id: r for r in rows}
    assert by_id[a.id].is_backed_up is True
    assert by_id[b.id].is_backed_up is False


@pytest.mark.django_db
def test_list_series_items_unknown_series_raises(tmp_path):
    root = tmp_path / "lib"
    root.mkdir()
    with pytest.raises(ValueError, match="Series not found"):
        list_series_items(manga_root=str(root), series_id=999)


@pytest.mark.django_db
def test_get_series_returns_row(tmp_path, monkeypatch):
    root = tmp_path / "lib"
    root.mkdir()
    (root / "S").mkdir()
    (root / "S" / "ch.cbz").write_bytes(b"x")
    monkeypatch.setattr(manga_services, "list_dropbox_files", lambda _path: [])
    sync_manga_library_cache(manga_root=str(root))
    s = Series.objects.get(library_root=str(root.resolve()), series_rel_path="S")
    got = get_series(manga_root=str(root), series_id=s.id)
    assert got.pk == s.pk
    assert got.name == s.name


@pytest.mark.django_db
def test_get_series_wrong_library_raises(tmp_path):
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    root_a.mkdir()
    root_b.mkdir()
    abs_a = str(root_a.resolve())
    s = Series.objects.create(
        library_root=abs_a,
        series_rel_path="s",
        name="s",
    )
    with pytest.raises(ValueError, match="Series not found"):
        get_series(manga_root=str(root_b.resolve()), series_id=s.id)


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
def test_sync_manga_library_cache_deletes_cbz_jobs_before_stale_series(tmp_path, monkeypatch):
    """CbzConvertJob.series is PROTECT; sync must not fail when removing vanished series rows."""
    root = tmp_path / "lib"
    root.mkdir()
    (root / "OldSeries").mkdir()
    (root / "OldSeries" / "a.cbz").write_bytes(b"x")
    (root / "KeptSeries").mkdir()
    (root / "KeptSeries" / "b.cbz").write_bytes(b"y")
    monkeypatch.setattr(manga_services, "list_dropbox_files", lambda _path: [])

    sync_manga_library_cache(manga_root=str(root))
    abs_root = str(root.resolve())
    old = Series.objects.get(library_root=abs_root, series_rel_path="OldSeries")
    u = get_user_model().objects.create_user(username="sync_job_user", password="pw")
    CbzConvertJob.objects.create(
        user=u,
        manga_root=abs_root,
        series=old,
        series_item_id=999,
    )

    shutil.rmtree(root / "OldSeries")
    sync_manga_library_cache(manga_root=str(root))

    assert not Series.objects.filter(pk=old.pk).exists()
    assert Series.objects.filter(library_root=abs_root, series_rel_path="KeptSeries").exists()
    assert CbzConvertJob.objects.count() == 0


@pytest.mark.django_db
def test_convert_cbz_rejects_item_wrong_library(tmp_path, monkeypatch):
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    root_a.mkdir()
    root_b.mkdir()
    abs_a = str(root_a.resolve())
    s = Series.objects.create(library_root=abs_a, series_rel_path="s", name="s")
    row = SeriesItem.objects.create(series=s, rel_path="s/ch.cbz", filename="ch.cbz", size_bytes=0)
    monkeypatch.setattr(manga_services, "process_manga", lambda _paths, _wd: (_ for _ in ()).throw(AssertionError))

    with pytest.raises(ValueError, match="Item not found"):
        convert_cbz(manga_root=str(root_b), item_id=row.pk, kind="manga")


def test_first_cbz_page_as_base64_sorted_natural_order(tmp_path):
    cbz = tmp_path / "x.cbz"
    want = _minimal_jpeg_bytes()
    _write_cbz_member_bytes(cbz, {"010.jpg": b"old", "001.jpg": want})
    b64, mime = first_cbz_page_as_base64(str(cbz))
    assert mime == "image/jpeg"
    out = Image.open(BytesIO(base64.standard_b64decode(b64)))
    assert out.format == "JPEG"
    assert out.width == manga_services.COVER_THUMB_WIDTH


def test_first_cbz_page_as_base64_cover_thumb_tall_top_aligned(tmp_path):
    """Tall page: 11:17 crop keeps top (red), drops bottom (blue)."""
    w, h = 11, 34
    im = Image.new("RGB", (w, h))
    im.paste((255, 0, 0), (0, 0, w, h // 2))
    im.paste((0, 0, 255), (0, h // 2, w, h))
    buf = BytesIO()
    im.save(buf, format="PNG")
    cbz = tmp_path / "x.cbz"
    _write_cbz_member_bytes(cbz, {"001.png": buf.getvalue()})
    b64, mime = first_cbz_page_as_base64(str(cbz))
    assert mime == "image/jpeg"
    out = Image.open(BytesIO(base64.standard_b64decode(b64))).convert("RGB")
    assert out.width == manga_services.COVER_THUMB_WIDTH
    assert out.height == max(1, int(round(manga_services.COVER_THUMB_WIDTH * 17 / 11)))
    r, g, bpx = out.getpixel((out.width // 2, out.height - 1))
    assert r > 200 and g < 80 and bpx < 80


def test_first_cbz_page_as_base64_no_images_returns_none(tmp_path):
    cbz = tmp_path / "x.cbz"
    _write_minimal_cbz(cbz, ["readme.txt"])
    assert first_cbz_page_as_base64(str(cbz)) == (None, None)


def test_first_cbz_page_as_base64_skips_undecodable_uses_next_sorted_image(tmp_path):
    cbz = tmp_path / "x.cbz"
    want = _minimal_jpeg_bytes()
    _write_cbz_member_bytes(cbz, {"a.jpg": b"not jpeg", "b.jpg": want})
    b64, mime = first_cbz_page_as_base64(str(cbz))
    assert mime == "image/jpeg"
    assert b64 is not None
    out = Image.open(BytesIO(base64.standard_b64decode(b64)))
    assert out.format == "JPEG"
    assert out.width == manga_services.COVER_THUMB_WIDTH


@pytest.mark.django_db
def test_sync_manga_library_cache_sets_item_covers_from_each_cbz_first_page(tmp_path, monkeypatch):
    root = tmp_path / "lib"
    root.mkdir()
    (root / "S").mkdir()
    _write_cbz_member_bytes(root / "S" / "ch2.cbz", {"p.png": _minimal_jpeg_bytes()})
    _write_cbz_member_bytes(
        root / "S" / "ch1.cbz",
        {"b.jpg": b"skip", "a.jpg": _minimal_jpeg_bytes()},
    )
    monkeypatch.setattr(manga_services, "list_dropbox_files", lambda _path: [])

    sync_manga_library_cache(manga_root=str(root))
    for rel in ("S/ch1.cbz", "S/ch2.cbz"):
        row = SeriesItem.objects.get(rel_path=rel)
        assert row.cover_image_mime_type == "image/jpeg"
        assert row.cover_image_base64 is not None
        out = Image.open(BytesIO(base64.standard_b64decode(row.cover_image_base64)))
        assert out.format == "JPEG"


@pytest.mark.django_db
def test_sync_manga_library_cache_skips_item_cover_when_already_set(tmp_path, monkeypatch):
    root = tmp_path / "lib"
    root.mkdir()
    (root / "S").mkdir()
    _write_cbz_member_bytes(root / "S" / "ch.cbz", {"a.jpg": _minimal_jpeg_bytes()})
    monkeypatch.setattr(manga_services, "list_dropbox_files", lambda _path: [])

    calls = []

    def track(path: str):
        calls.append(path)
        return first_cbz_page_as_base64(path)

    monkeypatch.setattr(manga_services, "first_cbz_page_as_base64", track)

    abs_root = str(root.resolve())
    s = Series.objects.create(library_root=abs_root, series_rel_path="S", name="S")
    SeriesItem.objects.create(
        series=s,
        rel_path="S/ch.cbz",
        filename="ch.cbz",
        size_bytes=1,
        cover_image_base64="preset",
        cover_image_mime_type="image/jpeg",
    )

    sync_manga_library_cache(manga_root=str(root))
    row = SeriesItem.objects.get(rel_path="S/ch.cbz")
    assert row.cover_image_base64 == "preset"
    assert calls == [str((root / "S" / "ch.cbz").resolve())]


@pytest.mark.django_db
def test_sync_manga_library_cache_sets_cover_from_first_cbz_first_page(tmp_path, monkeypatch):
    root = tmp_path / "lib"
    root.mkdir()
    (root / "S").mkdir()
    page_bytes = b"\x89PNG\r\n\x1a\n"
    _write_cbz_member_bytes(root / "S" / "ch2.cbz", {"p.png": page_bytes})
    _write_cbz_member_bytes(
        root / "S" / "ch1.cbz",
        {"b.jpg": b"skip", "a.jpg": _minimal_jpeg_bytes()},
    )
    monkeypatch.setattr(manga_services, "list_dropbox_files", lambda _path: [])

    sync_manga_library_cache(manga_root=str(root))
    s = Series.objects.get(library_root=str(root.resolve()), series_rel_path="S")
    assert s.cover_image_mime_type == "image/jpeg"
    assert s.cover_image_base64 is not None
    out = Image.open(BytesIO(base64.standard_b64decode(s.cover_image_base64)))
    assert out.format == "JPEG"


@pytest.mark.django_db
def test_sync_series_items_for_cbz_path_refreshes_cover(tmp_path, monkeypatch):
    root = tmp_path / "lib"
    root.mkdir()
    (root / "S").mkdir()
    _write_cbz_member_bytes(root / "S" / "only.cbz", {"x.webp": _minimal_jpeg_bytes()})
    monkeypatch.setattr(manga_services, "list_dropbox_files", lambda _path: [])

    sync_series_items_for_cbz_path(manga_root=str(root), cbz_rel_path="S/only.cbz")
    s = Series.objects.get(library_root=str(root.resolve()), series_rel_path="S")
    assert s.cover_image_mime_type == "image/jpeg"
    assert s.cover_image_base64 is not None
    out = Image.open(BytesIO(base64.standard_b64decode(s.cover_image_base64)))
    assert out.format == "JPEG"


def test_clean_cbz_display_name_two_underscores_takes_middle_segment() -> None:
    assert clean_cbz_display_name("a_b_c.cbz") == "b.cbz"


def test_clean_cbz_display_name_one_underscore_takes_first_segment() -> None:
    assert clean_cbz_display_name("first_rest.cbz") == "first.cbz"


def test_clean_cbz_display_name_leading_hash_becomes_chapter() -> None:
    assert clean_cbz_display_name("#12.cbz") == "Chapter 12.cbz"


def test_clean_cbz_display_name_hash_with_space_after_no_extra_space() -> None:
    assert clean_cbz_display_name("# 99.cbz") == "Chapter 99.cbz"


def test_clean_cbz_display_name_hash_then_underscore_rules() -> None:
    """Two underscores: middle segment may start with #; Chapter applied after extraction."""
    assert clean_cbz_display_name("#a_b_c.cbz") == "b.cbz"
    assert clean_cbz_display_name("pre_#mid_suf.cbz") == "Chapter mid.cbz"


def test_clean_cbz_display_name_plain_no_change_returns_none() -> None:
    assert clean_cbz_display_name("plain.cbz") is None


@pytest.mark.django_db
def test_clean_series_item_filename_on_disk_renames_hash_prefix_to_chapter(tmp_path) -> None:
    root = tmp_path / "lib"
    root.mkdir()
    (root / "S").mkdir()
    (root / "S" / "#9.cbz").write_bytes(b"x")
    abs_root = str(root.resolve())
    series = Series.objects.create(library_root=abs_root, series_rel_path="S", name="S")
    item = SeriesItem.objects.create(
        series=series,
        rel_path="S/#9.cbz",
        filename="#9.cbz",
    )
    clean_series_item_filename_on_disk(item_id=item.pk)
    item.refresh_from_db()
    assert item.rel_path == "S/Chapter 9.cbz"
    assert item.filename == "Chapter 9.cbz"
    assert (root / "S" / "Chapter 9.cbz").is_file()
    assert not (root / "S" / "#9.cbz").exists()


@pytest.mark.django_db
def test_clean_series_item_filename_on_disk_renames_file_and_row(tmp_path) -> None:
    root = tmp_path / "lib"
    root.mkdir()
    (root / "S").mkdir()
    (root / "S" / "x_y_z.cbz").write_bytes(b"x")
    abs_root = str(root.resolve())
    series = Series.objects.create(library_root=abs_root, series_rel_path="S", name="S")
    item = SeriesItem.objects.create(
        series=series,
        rel_path="S/x_y_z.cbz",
        filename="x_y_z.cbz",
    )
    clean_series_item_filename_on_disk(item_id=item.pk)
    item.refresh_from_db()
    assert item.rel_path == "S/y.cbz"
    assert item.filename == "y.cbz"
    assert (root / "S" / "y.cbz").is_file()
    assert not (root / "S" / "x_y_z.cbz").exists()


@pytest.mark.django_db
def test_clean_series_item_filename_on_disk_errors_when_target_exists(tmp_path) -> None:
    root = tmp_path / "lib"
    root.mkdir()
    (root / "S").mkdir()
    (root / "S" / "x_y_z.cbz").write_bytes(b"a")
    (root / "S" / "y.cbz").write_bytes(b"b")
    abs_root = str(root.resolve())
    series = Series.objects.create(library_root=abs_root, series_rel_path="S", name="S")
    item = SeriesItem.objects.create(
        series=series,
        rel_path="S/x_y_z.cbz",
        filename="x_y_z.cbz",
    )
    with pytest.raises(ValueError, match="already exists"):
        clean_series_item_filename_on_disk(item_id=item.pk)
    assert (root / "S" / "x_y_z.cbz").is_file()


@pytest.mark.django_db
def test_series_is_fully_backed_up_vacuous_when_no_items(tmp_path) -> None:
    abs_root = str(tmp_path.resolve())
    s = Series.objects.create(library_root=abs_root, series_rel_path="S", name="S", item_count=0)
    assert s.is_fully_backed_up is True


@pytest.mark.django_db
def test_series_is_fully_backed_up_false_when_any_item_not_backed_up(tmp_path) -> None:
    abs_root = str(tmp_path.resolve())
    s = Series.objects.create(library_root=abs_root, series_rel_path="S", name="S", item_count=2)
    SeriesItem.objects.create(series=s, rel_path="S/a.cbz", filename="a.cbz", is_backed_up=True)
    SeriesItem.objects.create(series=s, rel_path="S/b.cbz", filename="b.cbz", is_backed_up=False)
    assert s.is_fully_backed_up is False


@pytest.mark.django_db
def test_list_series_annotates_is_fully_backed_up(tmp_path) -> None:
    abs_root = str(tmp_path.resolve())
    s = Series.objects.create(library_root=abs_root, series_rel_path="S", name="S", item_count=1)
    SeriesItem.objects.create(series=s, rel_path="S/a.cbz", filename="a.cbz", is_backed_up=True)
    rows = list_series(manga_root=abs_root)
    assert len(rows) == 1
    assert series_is_fully_backed_up_value(rows[0]) is True


@pytest.mark.django_db
def test_get_series_annotates_is_fully_backed_up(tmp_path) -> None:
    abs_root = str(tmp_path.resolve())
    s = Series.objects.create(library_root=abs_root, series_rel_path="S", name="S", item_count=1)
    SeriesItem.objects.create(series=s, rel_path="S/a.cbz", filename="a.cbz", is_backed_up=False)
    row = get_series(manga_root=abs_root, series_id=s.pk)
    assert series_is_fully_backed_up_value(row) is False