import pytest

from pagechecker.models import Category, Page, Question, Snapshot
from pagechecker.services import associate_questions_with_page, list_pages


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
def test_page_category_nullable_and_set():
    page = Page.objects.create(url="https://example.com/page-category")
    page.refresh_from_db()
    assert page.category_id is None

    cat = Category.objects.create(name="Tech", emoji="💻")
    page.category = cat
    page.save()
    page.refresh_from_db()
    assert page.category_id == cat.id
    assert page.category.name == "Tech"


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
