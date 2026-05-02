import pytest

from manga.services import list_manga_directories


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
