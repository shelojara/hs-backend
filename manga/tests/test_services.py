import pytest
from django.core.cache import cache
from django.test import override_settings

import manga.services as manga_services
from manga.models import MangaHiddenDirectory
from manga.services import (
    convert_cbz,
    invalidate_manga_directories_cache,
    list_manga_series,
    resolve_cbz_download,
)


@pytest.mark.django_db
def test_list_manga_series_missing_root_returns_empty_node(tmp_path):
    missing = tmp_path / "nope"
    node = list_manga_series(manga_root=str(missing))
    assert node.name == ""
    assert node.path == ""
    assert node.parent_name == ""
    assert node.children == ()


@pytest.mark.django_db
def test_list_manga_series_leaf_top_level_stays_at_root(tmp_path):
    root = tmp_path / "m"
    (root / "only_series").mkdir(parents=True)

    node = list_manga_series(manga_root=str(root))
    assert [c.name for c in node.children] == ["only_series"]
    assert node.children[0].path == "only_series"
    assert node.children[0].parent_name == ""


@pytest.mark.django_db
def test_list_manga_series_nested_only_dirs(tmp_path):
    root = tmp_path / "manga"
    (root / "a" / "b").mkdir(parents=True)
    (root / "c").mkdir()
    (root / "p" / "q" / "r").mkdir(parents=True)
    (root / "a" / "file.cbz").write_text("x")

    node = list_manga_series(manga_root=str(root))
    assert node.name == ""
    assert node.path == ""
    assert node.parent_name == ""

    # Top-level "a" skipped when it has subdirs; "b" promoted to root.
    by_name = {c.name: c for c in node.children}
    assert set(by_name) == {"b", "c", "q"}

    assert by_name["b"].path == "a/b"
    assert by_name["b"].parent_name == "a"
    assert by_name["b"].children == ()

    assert by_name["c"].path == "c"
    assert by_name["c"].parent_name == ""
    assert by_name["c"].children == ()

    assert by_name["q"].path == "p/q"
    assert by_name["q"].parent_name == "p"
    assert len(by_name["q"].children) == 1
    deep = by_name["q"].children[0]
    assert deep.name == "r"
    assert deep.path == "p/q/r"
    assert deep.parent_name == "q"


@pytest.mark.django_db
def test_list_manga_series_skips_dot_dirs(tmp_path):
    root = tmp_path / "m"
    (root / "visible").mkdir(parents=True)
    (root / ".hidden").mkdir()

    node = list_manga_series(manga_root=str(root))
    names = [c.name for c in node.children]
    assert ".hidden" not in names
    assert "visible" in names


@pytest.mark.django_db
def test_list_manga_series_uses_cache_between_calls(tmp_path, monkeypatch):
    root = tmp_path / "m"
    root.mkdir()
    calls = {"n": 0}
    real = manga_services._manga_directory_subtree

    def wrapped(full_path: str, *, rel_posix: str, hidden):
        calls["n"] += 1
        return real(full_path, rel_posix=rel_posix, hidden=hidden)

    monkeypatch.setattr(manga_services, "_manga_directory_subtree", wrapped)
    list_manga_series(manga_root=str(root))
    list_manga_series(manga_root=str(root))
    assert calls["n"] == 1


def _dir_cache_key(manga_root: str) -> str:
    return manga_services._manga_directories_cache_key(
        manga_root,
        hidden=manga_services._manga_hidden_rel_paths(),
    )


@pytest.mark.django_db
def test_invalidate_manga_directories_cache_forces_series_rebuild(tmp_path, monkeypatch):
    root = tmp_path / "m"
    root.mkdir()
    calls = {"n": 0}
    real = manga_services._manga_directory_subtree

    def wrapped(full_path: str, *, rel_posix: str, hidden):
        calls["n"] += 1
        return real(full_path, rel_posix=rel_posix, hidden=hidden)

    monkeypatch.setattr(manga_services, "_manga_directory_subtree", wrapped)
    list_manga_series(manga_root=str(root))
    invalidate_manga_directories_cache(manga_root=str(root))
    list_manga_series(manga_root=str(root))
    assert calls["n"] == 2


@pytest.mark.django_db
def test_list_manga_series_hides_configured_paths(tmp_path):
    root = tmp_path / "m"
    (root / "keep").mkdir(parents=True)
    (root / "hide_me").mkdir()
    (root / "hide_me" / "nested").mkdir()
    MangaHiddenDirectory.objects.create(rel_path="hide_me")

    node = list_manga_series(manga_root=str(root))
    names = [c.name for c in node.children]
    assert names == ["keep"]


@pytest.mark.django_db
def test_list_manga_series_hidden_top_level_not_promoted(tmp_path):
    root = tmp_path / "m"
    (root / "keep").mkdir(parents=True)
    (root / "series" / "visible").mkdir(parents=True)
    MangaHiddenDirectory.objects.create(rel_path="series")

    node = list_manga_series(manga_root=str(root))
    assert [c.name for c in node.children] == ["keep"]


@pytest.mark.django_db
def test_list_manga_series_hides_prefix_under_parent(tmp_path):
    root = tmp_path / "m"
    (root / "series" / "visible").mkdir(parents=True)
    (root / "series" / "old" / "x").mkdir(parents=True)
    MangaHiddenDirectory.objects.create(rel_path="series/old")

    node = list_manga_series(manga_root=str(root))
    visible = next(c for c in node.children if c.name == "visible")
    assert visible.path == "series/visible"
    assert visible.parent_name == "series"
    assert visible.children == ()


@pytest.mark.django_db
@override_settings(MANGA_DIRECTORIES_CACHE_TIMEOUT_SECONDS=3600)
def test_convert_cbz_invalidates_directories_cache(tmp_path, monkeypatch):
    root = tmp_path / "m"
    root.mkdir()
    cbz = root / "series" / "ch.cbz"
    cbz.parent.mkdir(parents=True)
    cbz.write_bytes(b"PK\x03\x04")

    monkeypatch.setattr(manga_services, "process_manga", lambda _paths: str(cbz))
    monkeypatch.setattr(manga_services, "upload_to_dropbox", lambda *_a, **_k: None)

    root_str = str(root)
    list_manga_series(manga_root=root_str)
    key = _dir_cache_key(root_str)
    assert cache.get(key) is not None

    convert_cbz(manga_root=root_str, path="series/ch.cbz", kind="manga")
    assert manga_services._manga_directories_cache_ver(root_str) == 1
    assert cache.get(_dir_cache_key(root_str)) is None


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
def test_convert_cbz_rejects_path_escape(tmp_path, monkeypatch):
    root = tmp_path / "m"
    root.mkdir()
    monkeypatch.setattr(manga_services, "process_manga", lambda _paths: (_ for _ in ()).throw(AssertionError))

    with pytest.raises(ValueError, match="outside manga root"):
        convert_cbz(manga_root=str(root), path="../evil.cbz", kind="manga")
