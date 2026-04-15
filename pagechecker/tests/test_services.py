from unittest.mock import patch

import pytest

from pagechecker.models import Category, Page, Question, Snapshot
from pagechecker.services import (
    associate_questions_with_page,
    list_pages,
    update_page,
)


@pytest.mark.django_db
def test_associate_questions_with_page_replaces_skips_unknown_clears_empty():
    page = Page.objects.create(url="https://example.com/associate-m2m-test")
    q1 = Question.objects.create(text="one")
    q2 = Question.objects.create(text="two")
    q3 = Question.objects.create(text="three")

    associate_questions_with_page(page.id, [q1.id, q2.id])
    page.refresh_from_db()
    assert set(page.questions.values_list("id", flat=True)) == {q1.id, q2.id}

    associate_questions_with_page(page.id, [q2.id, q3.id])
    page.refresh_from_db()
    assert set(page.questions.values_list("id", flat=True)) == {q2.id, q3.id}

    associate_questions_with_page(page.id, [q1.id, 999_999])
    page.refresh_from_db()
    assert set(page.questions.values_list("id", flat=True)) == {q1.id}

    associate_questions_with_page(page.id, [])
    page.refresh_from_db()
    assert list(page.questions.values_list("id", flat=True)) == []


@pytest.mark.django_db
def test_list_pages_newest_first():
    older = Page.objects.create(url="https://example.com/list-pages-older")
    newer = Page.objects.create(url="https://example.com/list-pages-newer")
    assert [p.id for p in list_pages(limit=10, offset=0)] == [newer.id, older.id]


@pytest.mark.django_db
def test_category_name_and_emoji():
    cat = Category.objects.create(name="News", emoji="📰")
    cat.refresh_from_db()
    assert cat.name == "News"
    assert cat.emoji == "📰"
    assert str(cat) == "News"


@pytest.mark.django_db
@patch("pagechecker.services.check_page")
def test_update_page_sets_category_when_category_id_given(mock_check):
    cat = Category.objects.create(name="Docs", emoji="📄")
    page = Page.objects.create(url="https://example.com/update-cat")
    update_page(
        page.id,
        "https://example.com/update-cat-new",
        category_id=cat.id,
    )
    page.refresh_from_db()
    assert page.url == "https://example.com/update-cat-new"
    assert page.category_id == cat.id
    mock_check.assert_called_once_with(page.id)


@pytest.mark.django_db
@patch("pagechecker.services.check_page")
def test_update_page_preserves_category_when_same_category_id(mock_check):
    cat = Category.objects.create(name="Docs", emoji="📄")
    page = Page.objects.create(url="https://example.com/keep-cat", category=cat)
    update_page(page.id, "https://example.com/keep-cat-new", category_id=cat.id)
    page.refresh_from_db()
    assert page.category_id == cat.id
    mock_check.assert_called_once_with(page.id)


@pytest.mark.django_db
@patch("pagechecker.services.check_page")
def test_update_page_category_id_none_clears_category(mock_check):
    cat = Category.objects.create(name="Docs", emoji="📄")
    page = Page.objects.create(url="https://example.com/clear-cat", category=cat)
    update_page(page.id, "https://example.com/clear-cat-new", category_id=None)
    page.refresh_from_db()
    assert page.category_id is None
    mock_check.assert_called_once_with(page.id)


@pytest.mark.django_db
def test_snapshot_has_no_features_field():
    page = Page.objects.create(url="https://example.com/snapshot-no-features")
    snap = Snapshot.objects.create(
        page=page,
        html_content="<p>x</p>",
        md_content="# x",
    )
    assert snap.md_content == "# x"
    assert "features" not in [f.name for f in Snapshot._meta.get_fields()]
