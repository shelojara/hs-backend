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
    change_page_url,
    check_page,
    create_category,
    list_categories,
    list_pages,
    run_daily_report_for_page,
    send_daily_reports,
    set_page_category,
    set_page_should_report_daily,
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
def test_change_page_url_skips_check_when_url_unchanged(mock_check):
    page = Page.objects.create(url="https://example.com/same-url")
    change_page_url(page.id, "https://example.com/same-url")
    page.refresh_from_db()
    assert page.url == "https://example.com/same-url"
    mock_check.assert_not_called()


@pytest.mark.django_db
@patch("pagechecker.services.check_page")
def test_set_page_category_sets_category_when_category_id_given(mock_check):
    cat = Category.objects.create(name="Docs", emoji="📄")
    page = Page.objects.create(url="https://example.com/update-cat")
    set_page_category(page.id, category_id=cat.id)
    page.refresh_from_db()
    assert page.url == "https://example.com/update-cat"
    assert page.category_id == cat.id
    mock_check.assert_not_called()


@pytest.mark.django_db
@patch("pagechecker.services.check_page")
def test_set_page_category_preserves_category_when_same_category_id(mock_check):
    cat = Category.objects.create(name="Docs", emoji="📄")
    page = Page.objects.create(url="https://example.com/keep-cat", category=cat)
    set_page_category(page.id, category_id=cat.id)
    page.refresh_from_db()
    assert page.category_id == cat.id
    mock_check.assert_not_called()


@pytest.mark.django_db
@patch("pagechecker.services.check_page")
def test_set_page_category_none_clears_category(mock_check):
    cat = Category.objects.create(name="Docs", emoji="📄")
    page = Page.objects.create(url="https://example.com/clear-cat", category=cat)
    set_page_category(page.id, category_id=None)
    page.refresh_from_db()
    assert page.category_id is None
    mock_check.assert_not_called()


@pytest.mark.django_db
@patch("pagechecker.services.check_page")
def test_set_page_should_report_daily_updates_flag_only(mock_check):
    page = Page.objects.create(
        url="https://example.com/daily-only",
        should_report_daily=False,
    )
    set_page_should_report_daily(page.id, should_report_daily=True)
    page.refresh_from_db()
    assert page.should_report_daily is True
    mock_check.assert_not_called()


@pytest.mark.django_db
@patch("pagechecker.services.check_page")
def test_change_page_url_calls_check_when_url_changes(mock_check):
    page = Page.objects.create(url="https://example.com/old")
    change_page_url(page.id, "https://example.com/new")
    page.refresh_from_db()
    assert page.url == "https://example.com/new"
    mock_check.assert_called_once_with(page.id)


@pytest.mark.django_db
@patch("pagechecker.services.check_page")
def test_change_page_url_deletes_snapshots_unless_keep(mock_check):
    page = Page.objects.create(url="https://example.com/url-snap")
    Snapshot.objects.create(page=page, html_content="<p>a</p>", md_content="a")
    change_page_url(page.id, "https://example.com/url-snap-new", keep_snapshots=False)
    assert page.snapshots.count() == 0
    mock_check.assert_called_once_with(page.id)


@pytest.mark.django_db
@patch("pagechecker.services.check_page")
def test_change_page_url_keeps_snapshots_when_requested(mock_check):
    page = Page.objects.create(url="https://example.com/url-keep")
    Snapshot.objects.create(page=page, html_content="<p>a</p>", md_content="a")
    change_page_url(page.id, "https://example.com/url-keep-new", keep_snapshots=True)
    assert page.snapshots.count() == 1
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
def test_set_page_category_api_updates_category():
    User.objects.create_user(username="setcat", password="secretcat")
    cat = Category.objects.create(name="Docs", emoji="📄")
    page = Page.objects.create(url="https://example.com/api-cat")

    api_client = Client()
    login_resp = api_client.post(
        "/api/v1.Auth.Login",
        data=json.dumps({"username": "setcat", "password": "secretcat"}),
        content_type="application/json",
    )
    assert login_resp.status_code == 200
    token = login_resp.json()["access_token"]

    resp = api_client.post(
        "/api/v1.PageChecker.SetPageCategory",
        data=json.dumps({"page_id": page.id, "category_id": cat.id}),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert resp.status_code == 200
    page.refresh_from_db()
    assert page.category_id == cat.id


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


@pytest.mark.django_db
@patch("pagechecker.scheduled_tasks.enqueue_daily_report_jobs")
def test_send_daily_reports_passes_force_to_enqueue(mock_enqueue):
    mock_enqueue.return_value = [7, 8]
    assert send_daily_reports(force=False) == [7, 8]
    mock_enqueue.assert_called_once_with(skip_time_zone_check=False)
    mock_enqueue.reset_mock()
    assert send_daily_reports(force=True) == [7, 8]
    mock_enqueue.assert_called_once_with(skip_time_zone_check=True)


@pytest.mark.django_db
def test_send_daily_reports_api_enqueues_and_returns_ids():
    User.objects.create_user(username="dailyapi", password="pw")
    p = Page.objects.create(
        url="https://example.com/daily-api",
        should_report_daily=True,
    )
    api_client = Client()
    login_resp = api_client.post(
        "/api/v1.Auth.Login",
        data=json.dumps({"username": "dailyapi", "password": "pw"}),
        content_type="application/json",
    )
    assert login_resp.status_code == 200
    token = login_resp.json()["access_token"]

    with patch("pagechecker.services.send_daily_reports", return_value=[p.id]) as mock_send:
        resp = api_client.post(
            "/api/v1.PageChecker.SendDailyReports",
            data=json.dumps({"force": True}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
    assert resp.status_code == 200
    assert resp.json() == {"enqueued_page_ids": [p.id]}
    mock_send.assert_called_once_with(force=True)


@pytest.mark.django_db
@patch("pagechecker.services.send_email_via_gmail")
@patch("pagechecker.services.compare_snapshots")
@patch("pagechecker.services.check_page")
def test_run_daily_report_for_page_emails_check_status_and_answers(
    mock_check, mock_compare, mock_send,
):
    User.objects.create_user(
        username="daily_reader",
        password="pw",
        email="reader@example.com",
    )
    page = Page.objects.create(
        url="https://example.com/daily-report",
        title="Daily Page",
        should_report_daily=True,
    )
    q1 = Question.objects.create(text="What changed?")
    q2 = Question.objects.create(text="Any risks?")
    associate_questions_with_page(page.id, [q1.id, q2.id])

    mock_check.return_value = False
    mock_compare.side_effect = ["Nothing major.", "No risks."]

    run_daily_report_for_page(page.id)

    mock_check.assert_called_once_with(page.id)
    assert mock_compare.call_count == 2
    assert {(c.args[0], c.args[1]) for c in mock_compare.call_args_list} == {
        (page.id, q1.text),
        (page.id, q2.text),
    }
    mock_send.assert_called_once()
    kwargs = mock_send.call_args.kwargs
    assert kwargs["to_addrs"] == ["reader@example.com"]
    assert "Daily Page" in kwargs["subject"]
    body = kwargs["body"]
    assert "no content change" in body
    assert "Q: What changed?" in body and "A: Nothing major." in body
    assert "Q: Any risks?" in body and "A: No risks." in body


@pytest.mark.django_db
@patch("pagechecker.services.send_email_via_gmail")
@patch("pagechecker.services.compare_snapshots")
@patch("pagechecker.services.check_page")
def test_run_daily_report_for_page_check_failure_still_runs_questions_and_emails(
    mock_check, mock_compare, mock_send,
):
    User.objects.create_user(
        username="u_a",
        password="pw",
        email="a@example.com",
    )
    User.objects.create_user(
        username="u_b",
        password="pw",
        email="b@example.com",
    )
    page = Page.objects.create(url="https://example.com/daily-fail")
    q = Question.objects.create(text="Still ask?")
    associate_questions_with_page(page.id, [q.id])
    mock_check.side_effect = RuntimeError("network down")
    mock_compare.return_value = "ok"

    run_daily_report_for_page(page.id)

    mock_compare.assert_called_once()
    mock_send.assert_called_once()
    kwargs = mock_send.call_args.kwargs
    assert set(kwargs["to_addrs"]) == {"a@example.com", "b@example.com"}
    body = kwargs["body"]
    assert "failed" in body and "network down" in body
    assert "A: ok" in body


@pytest.mark.django_db
@patch("pagechecker.services.send_email_via_gmail")
@patch("pagechecker.services.compare_snapshots")
@patch("pagechecker.services.check_page")
def test_run_daily_report_for_page_question_error_in_body(
    mock_check, mock_compare, mock_send,
):
    User.objects.create_user(
        username="qerr_reader",
        password="pw",
        email="x@example.com",
    )
    page = Page.objects.create(url="https://example.com/daily-qerr")
    q = Question.objects.create(text="Bad?")
    associate_questions_with_page(page.id, [q.id])
    mock_check.return_value = True
    mock_compare.side_effect = ValueError("no snapshots")

    run_daily_report_for_page(page.id)

    mock_send.assert_called_once()
    assert "Error: no snapshots" in mock_send.call_args.kwargs["body"]


@pytest.mark.django_db
@patch("pagechecker.services.send_email_via_gmail")
@patch("pagechecker.services.compare_snapshots")
@patch("pagechecker.services.check_page")
def test_run_daily_report_for_page_skips_email_when_no_user_emails(
    mock_check, mock_compare, mock_send,
):
    User.objects.create_user(
        username="no_email_user",
        password="pw",
        email="",
    )
    page = Page.objects.create(url="https://example.com/daily-no-mail")
    mock_check.return_value = False

    run_daily_report_for_page(page.id)

    mock_send.assert_not_called()


@pytest.mark.django_db
@patch("pagechecker.services.send_email_via_gmail")
@patch("pagechecker.services.compare_snapshots")
@patch("pagechecker.services.check_page")
def test_run_daily_report_dedupes_same_email_across_users(
    mock_check, mock_compare, mock_send,
):
    User.objects.create_user(
        username="dup_a",
        password="pw",
        email="reader@example.com",
    )
    User.objects.create_user(
        username="dup_b",
        password="pw",
        email="reader@example.com",
    )
    page = Page.objects.create(url="https://example.com/daily-dedup")
    mock_check.return_value = False

    run_daily_report_for_page(page.id)

    mock_send.assert_called_once()
    assert mock_send.call_args.kwargs["to_addrs"] == ["reader@example.com"]


@pytest.mark.django_db
@patch("pagechecker.services.send_email_via_gmail")
@patch("pagechecker.services.compare_snapshots")
@patch("pagechecker.services.check_page")
def test_run_daily_report_ignores_inactive_users(mock_check, mock_compare, mock_send):
    User.objects.create_user(
        username="inactive",
        password="pw",
        email="gone@example.com",
        is_active=False,
    )
    page = Page.objects.create(url="https://example.com/daily-inactive-only")
    mock_check.return_value = False

    run_daily_report_for_page(page.id)

    mock_send.assert_not_called()
