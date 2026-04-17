from unittest.mock import patch

import httpx
import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from pagechecker.models import Category, Page, Question, ReportInterval, Snapshot
from pagechecker.services import (
    MonitoredUrlNotFoundError,
    QuestionInUseError,
    associate_questions_with_page,
    change_page_url,
    check_page,
    create_category,
    create_page,
    delete_question,
    list_categories,
    list_pages,
    run_daily_report_for_page,
    send_daily_reports,
    send_monthly_reports,
    send_weekly_reports,
    set_page_category,
    set_page_feature_instruction,
    set_page_report_interval,
)

User = get_user_model()


def _owner(username: str = "owner", **kwargs):
    return User.objects.create_user(username=username, password="pw", **kwargs)


@pytest.mark.django_db
def test_associate_questions_with_page_replaces_skips_unknown_clears_empty():
    user = _owner()
    page = Page.objects.create(
        url="https://example.com/associate-m2m-test",
        owner=user,
    )
    q1 = Question.objects.create(text="one", owner=user)
    q2 = Question.objects.create(text="two", owner=user)
    q3 = Question.objects.create(text="three", owner=user)

    associate_questions_with_page(page.id, [q1.id, q2.id], user_id=user.pk)
    page.refresh_from_db()
    assert set(page.questions.values_list("id", flat=True)) == {q1.id, q2.id}

    associate_questions_with_page(page.id, [q2.id, q3.id], user_id=user.pk)
    page.refresh_from_db()
    assert set(page.questions.values_list("id", flat=True)) == {q2.id, q3.id}

    associate_questions_with_page(page.id, [q1.id, 999_999], user_id=user.pk)
    page.refresh_from_db()
    assert set(page.questions.values_list("id", flat=True)) == {q1.id}

    associate_questions_with_page(page.id, [], user_id=user.pk)
    page.refresh_from_db()
    assert list(page.questions.values_list("id", flat=True)) == []


@pytest.mark.django_db
def test_delete_question_blocked_when_linked_to_page():
    user = _owner()
    page = Page.objects.create(url="https://example.com/q-guard", owner=user)
    q = Question.objects.create(text="linked", owner=user)
    associate_questions_with_page(page.id, [q.id], user_id=user.pk)
    with pytest.raises(QuestionInUseError):
        delete_question(q.id, user_id=user.pk)
    assert Question.objects.filter(id=q.id).exists()


@pytest.mark.django_db
def test_delete_question_ok_when_not_linked():
    user = _owner()
    q = Question.objects.create(text="orphan", owner=user)
    delete_question(q.id, user_id=user.pk)
    assert not Question.objects.filter(id=q.id).exists()


@pytest.mark.django_db
def test_delete_question_noop_when_missing_id():
    user = _owner()
    delete_question(999_999, user_id=user.pk)


@pytest.mark.django_db
def test_list_pages_newest_first():
    user = _owner()
    older = Page.objects.create(
        url="https://example.com/list-pages-older",
        owner=user,
    )
    newer = Page.objects.create(
        url="https://example.com/list-pages-newer",
        owner=user,
    )
    assert [p.id for p in list_pages(user_id=user.pk, limit=10, offset=0)] == [
        newer.id,
        older.id,
    ]


@pytest.mark.django_db
def test_list_pages_scoped_to_owner():
    a = _owner()
    b = _owner(username="other")
    pa = Page.objects.create(url="https://example.com/a-only", owner=a)
    Page.objects.create(url="https://example.com/b-only", owner=b)
    assert [p.id for p in list_pages(user_id=a.pk)] == [pa.id]


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


def _fake_check_page_with_snapshot(page_id: int) -> bool:
    page = Page.objects.get(id=page_id)
    Snapshot.objects.create(
        page=page,
        html_content="<p>x</p>",
        md_content="# snapshot body",
    )
    Page.objects.filter(id=page_id).update(
        title="Titled",
        last_checked_at=timezone.now(),
    )
    return True


@pytest.mark.django_db
@patch("pagechecker.services.gemini_service.suggest_page_category_id", return_value=None)
@patch("pagechecker.services.check_page", side_effect=_fake_check_page_with_snapshot)
def test_create_page_passes_categories_and_url_title_to_gemini(mock_check, mock_suggest):
    user = _owner()
    cat = Category.objects.create(name="Docs", emoji="📄")
    Page.objects.create(
        url="https://example.com/existing-doc",
        title="API Reference",
        category=cat,
        owner=user,
    )

    page_id = create_page("https://example.com/new-doc", user_id=user.pk)

    mock_check.assert_called_once_with(page_id)
    page = Page.objects.get(id=page_id)
    assert page.category_id is None
    mock_suggest.assert_called_once()
    kwargs = mock_suggest.call_args.kwargs
    assert kwargs["page_url"] == "https://example.com/new-doc"
    assert kwargs["page_title"] == "Titled"
    assert "page_content_excerpt" not in kwargs
    assert kwargs["categories"]
    docs_block = next(b for b in kwargs["categories"] if b["id"] == cat.id)
    assert docs_block["name"] == "Docs"
    assert any(
        ex["url"] == "https://example.com/existing-doc"
        for ex in docs_block["examples"]
    )


@pytest.mark.django_db
@patch("pagechecker.services.gemini_service.suggest_page_category_id", return_value=None)
@patch("pagechecker.services.check_page", side_effect=_fake_check_page_with_snapshot)
def test_create_page_new_page_excluded_from_peer_examples(mock_check, mock_suggest):
    user = _owner()
    cat = Category.objects.create(name="Docs", emoji="📄")
    Page.objects.create(
        url="https://example.com/peer",
        title="Peer",
        category=cat,
        owner=user,
    )
    new_url = "https://example.com/brand-new"
    create_page(new_url, user_id=user.pk)

    kwargs = mock_suggest.call_args.kwargs
    block = next(b for b in kwargs["categories"] if b["id"] == cat.id)
    urls = {ex["url"] for ex in block["examples"]}
    assert "https://example.com/peer" in urls
    assert new_url not in urls


@pytest.mark.django_db
@patch("pagechecker.services.gemini_service.suggest_page_category_id")
@patch("pagechecker.services.check_page", side_effect=_fake_check_page_with_snapshot)
def test_create_page_no_categories_skips_gemini(mock_check, mock_suggest):
    user = _owner()
    page_id = create_page("https://example.com/lone", user_id=user.pk)

    mock_check.assert_called_once_with(page_id)
    mock_suggest.assert_not_called()
    assert Page.objects.get(id=page_id).category_id is None


@pytest.mark.django_db
@patch("pagechecker.services.gemini_service.suggest_page_category_id", return_value=None)
@patch("pagechecker.services.check_page", side_effect=_fake_check_page_with_snapshot)
def test_create_page_gemini_none_leaves_uncategorized(mock_check, mock_suggest):
    user = _owner()
    Category.objects.create(name="Docs", emoji="📄")
    page_id = create_page("https://example.com/none-cat", user_id=user.pk)

    mock_suggest.assert_called_once()
    assert Page.objects.get(id=page_id).category_id is None


@pytest.mark.django_db
@patch(
    "pagechecker.services.gemini_service.suggest_page_category_id",
    return_value=None,
)
@patch("pagechecker.services.check_page", side_effect=_fake_check_page_with_snapshot)
def test_create_page_sets_category_when_gemini_returns_id(mock_check, mock_suggest):
    user = _owner()
    cat = Category.objects.create(name="Docs", emoji="📄")
    mock_suggest.return_value = cat.id
    page_id = create_page("https://example.com/assigned", user_id=user.pk)

    assert Page.objects.get(id=page_id).category_id == cat.id


@pytest.mark.django_db
@patch("pagechecker.services.check_page")
def test_change_page_url_skips_check_when_url_unchanged(mock_check):
    user = _owner()
    page = Page.objects.create(url="https://example.com/same-url", owner=user)
    change_page_url(page.id, "https://example.com/same-url", user_id=user.pk)
    page.refresh_from_db()
    assert page.url == "https://example.com/same-url"
    mock_check.assert_not_called()


@pytest.mark.django_db
@patch("pagechecker.services.check_page")
def test_set_page_category_sets_category_when_category_id_given(mock_check):
    user = _owner()
    cat = Category.objects.create(name="Docs", emoji="📄")
    page = Page.objects.create(url="https://example.com/update-cat", owner=user)
    set_page_category(page.id, user_id=user.pk, category_id=cat.id)
    page.refresh_from_db()
    assert page.url == "https://example.com/update-cat"
    assert page.category_id == cat.id
    mock_check.assert_not_called()


@pytest.mark.django_db
@patch("pagechecker.services.check_page")
def test_set_page_category_preserves_category_when_same_category_id(mock_check):
    user = _owner()
    cat = Category.objects.create(name="Docs", emoji="📄")
    page = Page.objects.create(
        url="https://example.com/keep-cat",
        category=cat,
        owner=user,
    )
    set_page_category(page.id, user_id=user.pk, category_id=cat.id)
    page.refresh_from_db()
    assert page.category_id == cat.id
    mock_check.assert_not_called()


@pytest.mark.django_db
@patch("pagechecker.services.check_page")
def test_set_page_category_none_clears_category(mock_check):
    user = _owner()
    cat = Category.objects.create(name="Docs", emoji="📄")
    page = Page.objects.create(
        url="https://example.com/clear-cat",
        category=cat,
        owner=user,
    )
    set_page_category(page.id, user_id=user.pk, category_id=None)
    page.refresh_from_db()
    assert page.category_id is None
    mock_check.assert_not_called()


@pytest.mark.django_db
@patch("pagechecker.services.check_page")
def test_change_page_url_calls_check_when_url_changes(mock_check):
    user = _owner()
    page = Page.objects.create(url="https://example.com/old", owner=user)
    change_page_url(page.id, "https://example.com/new", user_id=user.pk)
    page.refresh_from_db()
    assert page.url == "https://example.com/new"
    mock_check.assert_called_once_with(page.id)


@pytest.mark.django_db
@patch("pagechecker.services.check_page")
def test_change_page_url_deletes_snapshots_unless_keep(mock_check):
    user = _owner()
    page = Page.objects.create(url="https://example.com/url-snap", owner=user)
    Snapshot.objects.create(page=page, html_content="<p>a</p>", md_content="a")
    change_page_url(
        page.id,
        "https://example.com/url-snap-new",
        user_id=user.pk,
        keep_snapshots=False,
    )
    assert page.snapshots.count() == 0
    mock_check.assert_called_once_with(page.id)


@pytest.mark.django_db
@patch("pagechecker.services.check_page")
def test_change_page_url_keeps_snapshots_when_requested(mock_check):
    user = _owner()
    page = Page.objects.create(url="https://example.com/url-keep", owner=user)
    Snapshot.objects.create(page=page, html_content="<p>a</p>", md_content="a")
    change_page_url(
        page.id,
        "https://example.com/url-keep-new",
        user_id=user.pk,
        keep_snapshots=True,
    )
    assert page.snapshots.count() == 1
    mock_check.assert_called_once_with(page.id)


@pytest.mark.django_db
def test_snapshot_feature_and_page_feature_instruction_nullable():
    user = _owner()
    page = Page.objects.create(
        url="https://example.com/snapshot-feature-fields",
        owner=user,
    )
    assert page.feature_instruction is None
    snap = Snapshot.objects.create(
        page=page,
        html_content="<p>x</p>",
        md_content="# x",
    )
    assert snap.md_content == "# x"
    assert snap.feature is None
    assert "features" not in [f.name for f in Snapshot._meta.get_fields()]
    page.feature_instruction = "summarize pricing"
    page.save(update_fields=["feature_instruction"])
    snap.feature = "pricing table"
    snap.save(update_fields=["feature"])
    page.refresh_from_db()
    snap.refresh_from_db()
    assert page.feature_instruction == "summarize pricing"
    assert snap.feature == "pricing table"


@pytest.mark.django_db
@patch("pagechecker.services.gemini_service.extract_snapshot_feature", return_value="Plan: Pro $9")
def test_check_page_sets_snapshot_feature_when_instruction_set(mock_extract):
    user = _owner()
    page = Page.objects.create(
        url="https://example.com/feature-snap",
        owner=user,
        feature_instruction="Summarize pricing",
    )
    html = """<!doctype html><html><head><title>Pricing</title></head>
    <body><p>Pro plan $9/mo</p></body></html>"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=html.encode(), request=request)

    transport = httpx.MockTransport(handler)

    def fake_get(url: str, verify: bool = False) -> httpx.Response:
        with httpx.Client(transport=transport) as client:
            return client.get(url)

    with patch("pagechecker.services.httpx.get", new=fake_get):
        check_page(page.id)

    snap = Snapshot.objects.filter(page=page).order_by("-created_at").first()
    assert snap is not None
    assert snap.feature == "Plan: Pro $9"
    mock_extract.assert_called_once()
    kwargs = mock_extract.call_args.kwargs
    assert kwargs["feature_instruction"] == "Summarize pricing"
    assert kwargs["page_url"] == "https://example.com/feature-snap"
    assert kwargs["page_title"] == "Pricing"
    assert "Pro plan" in kwargs["md_content"]
    assert kwargs["old_md_content"] is None
    assert kwargs["old_snapshot_taken_at"] is None
    assert kwargs["new_snapshot_taken_at"] is not None


@pytest.mark.django_db
@patch("pagechecker.services.gemini_service.extract_snapshot_feature", return_value="v2")
def test_check_page_passes_previous_snapshot_to_feature_extract(mock_extract):
    user = _owner()
    page = Page.objects.create(
        url="https://example.com/feature-dual",
        owner=user,
        feature_instruction="Summarize pricing",
    )
    snap1 = Snapshot.objects.create(
        page=page,
        html_content="<p>old</p>",
        md_content="# old md",
    )

    html2 = """<!doctype html><html><head><title>P2</title></head>
    <body><p>New price $5</p></body></html>"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=html2.encode(), request=request)

    transport = httpx.MockTransport(handler)

    def fake_get(url: str, verify: bool = False) -> httpx.Response:
        with httpx.Client(transport=transport) as client:
            return client.get(url)

    with patch("pagechecker.services.httpx.get", new=fake_get):
        check_page(page.id)

    kwargs = mock_extract.call_args.kwargs
    assert kwargs["old_md_content"] == "# old md"
    assert kwargs["old_snapshot_taken_at"] == snap1.created_at
    assert kwargs["new_snapshot_taken_at"] is not None
    assert "New price" in kwargs["md_content"]


@pytest.mark.django_db
@patch("pagechecker.services.gemini_service.extract_snapshot_feature")
def test_check_page_skips_feature_when_no_instruction(mock_extract):
    user = _owner()
    page = Page.objects.create(url="https://example.com/no-fi", owner=user)
    html = "<html><body><p>Hi</p></body></html>"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=html.encode(), request=request)

    transport = httpx.MockTransport(handler)

    def fake_get(url: str, verify: bool = False) -> httpx.Response:
        with httpx.Client(transport=transport) as client:
            return client.get(url)

    with patch("pagechecker.services.httpx.get", new=fake_get):
        check_page(page.id)

    snap = Snapshot.objects.get(page=page)
    assert snap.feature is None
    mock_extract.assert_not_called()


@pytest.mark.django_db
def test_check_page_raises_monitored_url_not_found_on_http_404():
    user = _owner()
    page = Page.objects.create(url="https://example.com/missing", owner=user)

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
def test_set_page_category_updates_category():
    user = _owner()
    cat = Category.objects.create(name="Docs", emoji="📄")
    page = Page.objects.create(url="https://example.com/svc-cat", owner=user)
    set_page_category(page.id, user_id=user.pk, category_id=cat.id)
    page.refresh_from_db()
    assert page.category_id == cat.id


@pytest.mark.django_db
def test_set_page_report_interval_sets_and_clears():
    user = _owner()
    page = Page.objects.create(url="https://example.com/svc-report-interval", owner=user)
    set_page_report_interval(page.id, user_id=user.pk, report_interval="WEEKLY")
    page.refresh_from_db()
    assert page.report_interval == "WEEKLY"
    set_page_report_interval(page.id, user_id=user.pk, report_interval="MONTHLY")
    page.refresh_from_db()
    assert page.report_interval == "MONTHLY"
    set_page_report_interval(page.id, user_id=user.pk, report_interval=None)
    page.refresh_from_db()
    assert page.report_interval is None


@pytest.mark.django_db
def test_set_page_feature_instruction_sets_strips_and_clears():
    user = _owner()
    page = Page.objects.create(
        url="https://example.com/svc-feature-instruction",
        owner=user,
        feature_instruction="old",
    )
    set_page_feature_instruction(
        page.id,
        user_id=user.pk,
        feature_instruction="  Focus on pricing  ",
    )
    page.refresh_from_db()
    assert page.feature_instruction == "Focus on pricing"
    set_page_feature_instruction(page.id, user_id=user.pk, feature_instruction=None)
    page.refresh_from_db()
    assert page.feature_instruction is None
    set_page_feature_instruction(page.id, user_id=user.pk, feature_instruction="x")
    page.refresh_from_db()
    assert page.feature_instruction == "x"
    set_page_feature_instruction(page.id, user_id=user.pk, feature_instruction="   ")
    page.refresh_from_db()
    assert page.feature_instruction is None


@pytest.mark.django_db
@patch("pagechecker.scheduled_tasks.enqueue_daily_report_jobs")
def test_send_daily_reports_delegates_to_enqueue(mock_enqueue):
    mock_enqueue.return_value = [7, 8]
    assert send_daily_reports() == [7, 8]
    mock_enqueue.assert_called_once_with()


@pytest.mark.django_db
@patch("pagechecker.scheduled_tasks.enqueue_weekly_report_jobs")
def test_send_weekly_reports_delegates_to_enqueue(mock_enqueue):
    mock_enqueue.return_value = [3, 4]
    assert send_weekly_reports() == [3, 4]
    mock_enqueue.assert_called_once_with()


@pytest.mark.django_db
@patch("pagechecker.scheduled_tasks.enqueue_monthly_report_jobs")
def test_send_monthly_reports_delegates_to_enqueue(mock_enqueue):
    mock_enqueue.return_value = [1, 2]
    assert send_monthly_reports() == [1, 2]
    mock_enqueue.assert_called_once_with()


@pytest.mark.django_db
@patch("pagechecker.services.send_email_via_gmail")
@patch("pagechecker.services.compare_snapshots")
@patch("pagechecker.services.check_page")
def test_run_daily_report_for_page_emails_check_status_and_answers(
    mock_check, mock_compare, mock_send,
):
    owner = User.objects.create_user(
        username="daily_reader",
        password="pw",
        email="reader@example.com",
    )
    page = Page.objects.create(
        url="https://example.com/daily-report",
        title="Daily Page",
        report_interval=ReportInterval.DAILY,
        owner=owner,
    )
    q1 = Question.objects.create(text="What changed?", owner=owner)
    q2 = Question.objects.create(text="Any risks?", owner=owner)
    associate_questions_with_page(page.id, [q1.id, q2.id], user_id=owner.pk)

    mock_check.return_value = False
    mock_compare.side_effect = ["Nothing major.", "No risks."]

    run_daily_report_for_page(page.id)

    mock_check.assert_called_once_with(page.id)
    assert mock_compare.call_count == 2
    assert {
        (c.args[0], c.args[1], c.kwargs.get("user_id"))
        for c in mock_compare.call_args_list
    } == {
        (page.id, q1.text, owner.pk),
        (page.id, q2.text, owner.pk),
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
def test_run_daily_report_includes_snapshot_feature_when_latest_has_feature(
    mock_check, mock_compare, mock_send,
):
    owner = User.objects.create_user(
        username="feat_reader",
        password="pw",
        email="feat@example.com",
    )
    page = Page.objects.create(
        url="https://example.com/daily-feature",
        title="Feat Page",
        owner=owner,
    )
    Snapshot.objects.create(
        page=page,
        md_content="# x",
        feature="Plan: Pro $9/mo",
    )
    q = Question.objects.create(text="Ok?", owner=owner)
    associate_questions_with_page(page.id, [q.id], user_id=owner.pk)
    mock_check.return_value = False
    mock_compare.return_value = "yes"

    run_daily_report_for_page(page.id)

    body = mock_send.call_args.kwargs["body"]
    assert "Snapshot feature: Plan: Pro $9/mo" in body


@pytest.mark.django_db
@patch("pagechecker.services.send_email_via_gmail")
@patch("pagechecker.services.compare_snapshots")
@patch("pagechecker.services.check_page")
def test_run_daily_report_omits_snapshot_feature_line_when_empty(
    mock_check, mock_compare, mock_send,
):
    owner = User.objects.create_user(
        username="no_feat_reader",
        password="pw",
        email="nf@example.com",
    )
    page = Page.objects.create(
        url="https://example.com/daily-no-feat",
        owner=owner,
    )
    Snapshot.objects.create(page=page, md_content="# x", feature=None)
    q = Question.objects.create(text="Ok?", owner=owner)
    associate_questions_with_page(page.id, [q.id], user_id=owner.pk)
    mock_check.return_value = False
    mock_compare.return_value = "yes"

    run_daily_report_for_page(page.id)

    body = mock_send.call_args.kwargs["body"]
    assert "Snapshot feature:" not in body


@pytest.mark.django_db
@patch("pagechecker.services.send_email_via_gmail")
@patch("pagechecker.services.compare_snapshots")
@patch("pagechecker.services.check_page")
def test_run_daily_report_for_page_check_failure_still_runs_questions_and_emails(
    mock_check, mock_compare, mock_send,
):
    owner = User.objects.create_user(
        username="u_a",
        password="pw",
        email="a@example.com",
    )
    page = Page.objects.create(url="https://example.com/daily-fail", owner=owner)
    q = Question.objects.create(text="Still ask?", owner=owner)
    associate_questions_with_page(page.id, [q.id], user_id=owner.pk)
    mock_check.side_effect = RuntimeError("network down")
    mock_compare.return_value = "ok"

    run_daily_report_for_page(page.id)

    mock_compare.assert_called_once()
    mock_send.assert_called_once()
    kwargs = mock_send.call_args.kwargs
    assert kwargs["to_addrs"] == ["a@example.com"]
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
    owner = User.objects.create_user(
        username="qerr_reader",
        password="pw",
        email="x@example.com",
    )
    page = Page.objects.create(url="https://example.com/daily-qerr", owner=owner)
    q = Question.objects.create(text="Bad?", owner=owner)
    associate_questions_with_page(page.id, [q.id], user_id=owner.pk)
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
    owner = User.objects.create_user(
        username="no_email_user",
        password="pw",
        email="",
    )
    page = Page.objects.create(url="https://example.com/daily-no-mail", owner=owner)
    mock_check.return_value = False

    run_daily_report_for_page(page.id)

    mock_send.assert_not_called()


@pytest.mark.django_db
@patch("pagechecker.services.send_email_via_gmail")
@patch("pagechecker.services.compare_snapshots")
@patch("pagechecker.services.check_page")
def test_run_daily_report_ignores_inactive_users(mock_check, mock_compare, mock_send):
    owner = User.objects.create_user(
        username="inactive",
        password="pw",
        email="gone@example.com",
        is_active=False,
    )
    page = Page.objects.create(url="https://example.com/daily-inactive-only", owner=owner)
    mock_check.return_value = False

    run_daily_report_for_page(page.id)

    mock_send.assert_not_called()
