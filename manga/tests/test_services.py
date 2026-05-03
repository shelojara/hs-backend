import base64
import zipfile
from io import BytesIO

import pytest
from PIL import Image

import manga.services as manga_services
from manga.models import MangaHiddenDirectory, Series, SeriesItem
from manga.services import (
    build_cbz_page_slice,
    convert_cbz,
    first_cbz_page_as_base64,
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
    abs_root = str(root.resolve())
    s = Series.objects.create(library_root=abs_root, series_rel_path="series", name="series")
    row = SeriesItem.objects.create(
        series=s,
        rel_path="series/ch.cbz",
        filename="ch.cbz",
        size_bytes=4,
    )

    calls = []

    def capture(**kw):
        calls.append(kw)

    monkeypatch.setattr(manga_services, "process_manga", lambda _paths: str(cbz))
    monkeypatch.setattr(manga_services, "upload_to_dropbox", lambda *_a, **_k: None)
    monkeypatch.setattr(manga_services, "sync_series_items_for_cbz_path", capture)

    convert_cbz(manga_root=str(root), item_id=row.pk, kind="manga")
    assert calls == [{"manga_root": str(root), "cbz_rel_path": "series/ch.cbz"}]


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
    assert items[0].filename == "c1.cbz"


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
    names = [r.filename for r in list_series_items(manga_root=str(root), series_id=s.id)]
    assert names == ["ch1.cbz", "ch2.cbz", "ch10.cbz"]


@pytest.mark.django_db
def test_list_series_items_filters_by_in_dropbox(tmp_path, monkeypatch):
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
    a.in_dropbox = True
    a.save(update_fields=["in_dropbox"])

    only_dropbox = list_series_items(
        manga_root=str(root), series_id=s.id, in_dropbox=True
    )
    assert [r.id for r in only_dropbox] == [a.id]

    not_dropbox = list_series_items(
        manga_root=str(root), series_id=s.id, in_dropbox=False
    )
    assert [r.id for r in not_dropbox] == [b.id]

    all_items = list_series_items(manga_root=str(root), series_id=s.id)
    assert {r.id for r in all_items} == {a.id, b.id}


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
def test_convert_cbz_rejects_item_wrong_library(tmp_path, monkeypatch):
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    root_a.mkdir()
    root_b.mkdir()
    abs_a = str(root_a.resolve())
    s = Series.objects.create(library_root=abs_a, series_rel_path="s", name="s")
    row = SeriesItem.objects.create(series=s, rel_path="s/ch.cbz", filename="ch.cbz", size_bytes=0)
    monkeypatch.setattr(manga_services, "process_manga", lambda _paths: (_ for _ in ()).throw(AssertionError))

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