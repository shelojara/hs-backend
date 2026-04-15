import json
from unittest.mock import MagicMock, patch

import httpx
import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from pagechecker.models import Category, Page, Question, Snapshot
from pagechecker.services import (
    MonitoredUrlNotFoundError,
    associate_questions_with_page,
    check_page,
    create_category,
    list_categories,
    list_pages,
    update_page,
)

User = get_user_model()


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
def test_list_categories_sorted_by_name_then_id():
    b = Category.objects.create(name="B", emoji="🐝")
    a = Category.objects.create(name="A", emoji="🐜")
    assert [c.id for c in list_categories()] == [a.id, b.id]


@pytest.mark.django_db
@patch("pagechecker.services.gemini_service.suggest_category_emoji", return_value="📰")
def test_create_category_persists_gemini_emoji(mock_emoji):
    cat = create_category("News")
    cat.refresh_from_db()
    assert cat.name == "News"
    assert cat.emoji == "📰"
    mock_emoji.assert_called_once_with("News")


@pytest.mark.django_db
@patch("pagechecker.services.check_page")
def test_update_page_skips_check_when_url_unchanged(mock_check):
    page = Page.objects.create(url="https://example.com/same-url")
    update_page(page.id, "https://example.com/same-url", should_report_daily=True)
    page.refresh_from_db()
    assert page.url == "https://example.com/same-url"
    assert page.should_report_daily is True
    mock_check.assert_not_called()


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
    update_page(
        page.id,
        "https://example.com/keep-cat-new",
        category_id=cat.id,
    )
    page.refresh_from_db()
    assert page.category_id == cat.id
    mock_check.assert_called_once_with(page.id)


@pytest.mark.django_db
@patch("pagechecker.services.check_page")
def test_update_page_category_id_none_clears_category(mock_check):
    cat = Category.objects.create(name="Docs", emoji="📄")
    page = Page.objects.create(url="https://example.com/clear-cat", category=cat)
    update_page(
        page.id,
        "https://example.com/clear-cat-new",
        category_id=None,
    )
    page.refresh_from_db()
    assert page.category_id is None
    mock_check.assert_called_once_with(page.id)


@pytest.mark.django_db
@patch("pagechecker.services.check_page")
def test_update_page_should_report_daily_defaults_false_when_omitted(mock_check):
    page = Page.objects.create(
        url="https://example.com/daily-omit",
        should_report_daily=True,
    )
    update_page(page.id, "https://example.com/daily-omit-new")
    page.refresh_from_db()
    assert page.should_report_daily is False
    mock_check.assert_called_once_with(page.id)


@pytest.mark.django_db
@patch("pagechecker.services.check_page")
def test_update_page_sets_should_report_daily(mock_check):
    page = Page.objects.create(
        url="https://example.com/daily-flag",
        should_report_daily=False,
    )
    update_page(
        page.id,
        "https://example.com/daily-flag-new",
        should_report_daily=True,
    )
    page.refresh_from_db()
    assert page.should_report_daily is True
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


@pytest.mark.django_db
def test_check_page_raises_monitored_url_not_found_on_http_404():
    page = Page.objects.create(url="https://example.com/missing")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, request=request)

    transport = httpx.MockTransport(handler)

    def fake_get(url: str, verify: bool = False) -> httpx.Response:
        with httpx.Client(transport=transport) as client:
            return client.get(url)

    with patch("pagechecker.services.httpx.get", new=fake_get):
        with pytest.raises(MonitoredUrlNotFoundError) as exc_info:
            check_page(page.id)
    assert "404" in str(exc_info.value)
    assert "Not Found" in str(exc_info.value)


@pytest.mark.django_db
def test_check_page_api_returns_clear_detail_on_remote_404():
    User.objects.create_user(username="check404", password="secret404")
    page = Page.objects.create(url="https://example.com/missing")

    api_client = Client()
    login_resp = api_client.post(
        "/api/v1.Auth.Login",
        data=json.dumps({"username": "check404", "password": "secret404"}),
        content_type="application/json",
    )
    assert login_resp.status_code == 200
    token = login_resp.json()["access_token"]

    with patch("pagechecker.services.httpx.get") as mock_get:
        mock_get.return_value = MagicMock(status_code=404, text="")
        check_resp = api_client.post(
            "/api/v1.PageChecker.CheckPage",
            data=json.dumps({"page_id": page.id}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

    assert check_resp.status_code == 404
    body = check_resp.json()
    assert "detail" in body
    assert "404" in body["detail"]
    assert "Not Found" in body["detail"]
