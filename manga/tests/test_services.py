import pytest

from manga.services import list_manga_directories


@pytest.mark.django_db
def test_list_manga_directories_missing_root_returns_empty(tmp_path):
    missing = tmp_path / "nope"
    assert list_manga_directories(manga_root=str(missing)) == []


@pytest.mark.django_db
def test_list_manga_directories_recursive_only_dirs(tmp_path):
    root = tmp_path / "manga"
    (root / "a" / "b").mkdir(parents=True)
    (root / "c").mkdir()
    (root / "a" / "file.cbz").write_text("x")

    got = list_manga_directories(manga_root=str(root))
    assert got == ["", "a", "a/b", "c"]


@pytest.mark.django_db
def test_list_manga_directories_skips_dot_dirs(tmp_path):
    root = tmp_path / "m"
    (root / "visible").mkdir(parents=True)
    (root / ".hidden").mkdir()

    got = list_manga_directories(manga_root=str(root))
    assert ".hidden" not in "".join(got)
    assert "" in got
    assert "visible" in got
