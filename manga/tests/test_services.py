import pytest
from django.core.cache import cache
from django.test import override_settings

import manga.services as manga_services
from manga.models import MangaHiddenDirectory
from manga.services import (
    convert_cbz,
    invalidate_manga_directories_cache,
    list_manga_directories,
    resolve_cbz_download,
)


@pytest.mark.django_db
def test_list_manga_directories_missing_root_returns_empty_node(tmp_path):
    missing = tmp_path / "nope"
    node = list_manga_directories(manga_root=str(missing))
    assert node.name == ""
    assert node.path == ""
    assert node.children == ()


@pytest.mark.django_db
def test_list_manga_directories_nested_only_dirs(tmp_path):
    root = tmp_path / "manga"
    (root / "a" / "b").mkdir(parents=True)
    (root / "c").mkdir()
    (root / "a" / "file.cbz").write_text("x")

    node = list_manga_directories(manga_root=str(root))
    assert node.name == ""
    assert node.path == ""

    by_name = {c.name: c for c in node.children}
    assert set(by_name) == {"a", "c"}

    a = by_name["a"]
    assert a.path == "a"
    assert len(a.children) == 1
    b = a.children[0]
    assert b.name == "b"
    assert b.path == "a/b"
    assert b.children == ()

    assert by_name["c"].path == "c"
    assert by_name["c"].children == ()


@pytest.mark.django_db
def test_list_manga_directories_skips_dot_dirs(tmp_path):
    root = tmp_path / "m"
    (root / "visible").mkdir(parents=True)
    (root / ".hidden").mkdir()

    node = list_manga_directories(manga_root=str(root))
    names = [c.name for c in node.children]
    assert ".hidden" not in names
    assert "visible" in names


@pytest.mark.django_db
def test_list_manga_directories_uses_cache_between_calls(tmp_path, monkeypatch):
    root = tmp_path / "m"
    root.mkdir()
    calls = {"n": 0}
    real = manga_services._manga_directory_subtree

    def wrapped(full_path: str, *, rel_posix: str, hidden):
        calls["n"] += 1
        return real(full_path, rel_posix=rel_posix, hidden=hidden)

    monkeypatch.setattr(manga_services, "_manga_directory_subtree", wrapped)
    list_manga_directories(manga_root=str(root))
    list_manga_directories(manga_root=str(root))
    assert calls["n"] == 1


def _dir_cache_key(manga_root: str) -> str:
    return manga_services._manga_directories_cache_key(
        manga_root,
        hidden=manga_services._manga_hidden_rel_paths(),
    )


@pytest.mark.django_db
def test_invalidate_manga_directories_cache_forces_rebuild(tmp_path, monkeypatch):
    root = tmp_path / "m"
    root.mkdir()
    calls = {"n": 0}
    real = manga_services._manga_directory_subtree

    def wrapped(full_path: str, *, rel_posix: str, hidden):
        calls["n"] += 1
        return real(full_path, rel_posix=rel_posix, hidden=hidden)

    monkeypatch.setattr(manga_services, "_manga_directory_subtree", wrapped)
    list_manga_directories(manga_root=str(root))
    invalidate_manga_directories_cache(manga_root=str(root))
    list_manga_directories(manga_root=str(root))
    assert calls["n"] == 2


@pytest.mark.django_db
def test_list_manga_directories_hides_configured_paths(tmp_path):
    root = tmp_path / "m"
    (root / "keep").mkdir(parents=True)
    (root / "hide_me").mkdir()
    (root / "hide_me" / "nested").mkdir()
    MangaHiddenDirectory.objects.create(rel_path="hide_me")

    node = list_manga_directories(manga_root=str(root))
    names = [c.name for c in node.children]
    assert names == ["keep"]


@pytest.mark.django_db
def test_list_manga_directories_hides_prefix_under_parent(tmp_path):
    root = tmp_path / "m"
    (root / "series" / "visible").mkdir(parents=True)
    (root / "series" / "old" / "x").mkdir(parents=True)
    MangaHiddenDirectory.objects.create(rel_path="series/old")

    node = list_manga_directories(manga_root=str(root))
    series = next(c for c in node.children if c.name == "series")
    child_names = [c.name for c in series.children]
    assert child_names == ["visible"]


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
    list_manga_directories(manga_root=root_str)
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
