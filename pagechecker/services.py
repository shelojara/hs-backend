import httpx
from django.db import transaction
from django.utils import timezone

from pagechecker import gemini_service
from pagechecker.html_utils import (
    extract_body_html,
    extract_metadata,
    html_to_markdown,
)
from pagechecker.models import Category, Page, Question, Snapshot


def page_ids_due_for_scheduled_check() -> list[int]:
    """All pages with *should_report_daily* (for daily scheduled dispatch)."""
    return list(
        Page.objects.filter(should_report_daily=True)
        .order_by("id")
        .values_list("id", flat=True)
    )


class MonitoredUrlNotFoundError(Exception):
    """Monitored URL responded with HTTP 404."""

    def __init__(self, message: str = "The monitored URL returned HTTP 404 (Not Found).") -> None:
        super().__init__(message)


def list_pages(limit: int = 20, offset: int = 0) -> list[Page]:
    qs = (
        Page.objects.order_by("-created_at")
        .select_related("category")
        .prefetch_related("questions")
    )
    return list(qs[offset : offset + limit])


def get_page(page_id: int) -> Page:
    return (
        Page.objects.select_related("category")
        .prefetch_related("questions")
        .get(id=page_id)
    )


def create_page(url: str) -> int:
    page = Page.objects.create(url=url)
    check_page(page.id)
    return page.id


@transaction.atomic
def change_page_url(
    page_id: int,
    url: str,
    *,
    keep_snapshots: bool = False,
) -> None:
    """Set page URL; purge snapshots unless *keep_snapshots*.

    When URL value changes, runs *check_page* to refresh title/icon and add snapshot.
    """
    page = Page.objects.select_for_update().get(id=page_id)
    old_url = page.url
    page.url = url
    page.save(update_fields=["url"])

    if not keep_snapshots:
        page.snapshots.all().delete()

    if old_url != url:
        check_page(page.id)


@transaction.atomic
def set_page_category(page_id: int, *, category_id: int | None = None) -> None:
    """Set page category FK only; does not touch daily-report flag or URL."""
    page = Page.objects.select_for_update().get(id=page_id)
    page.category_id = category_id
    page.save(update_fields=["category_id"])


@transaction.atomic
def set_page_should_report_daily(page_id: int, *, should_report_daily: bool) -> None:
    """Set daily-report flag only; leaves category and other fields unchanged."""
    page = Page.objects.select_for_update().get(id=page_id)
    page.should_report_daily = should_report_daily
    page.save(update_fields=["should_report_daily"])


def delete_page(page_id: int) -> None:
    Page.objects.filter(id=page_id).delete()


def check_page(page_id: int) -> bool:
    """Fetch the page, snapshot its text content, and return whether it changed."""
    page = Page.objects.get(id=page_id)

    response = httpx.get(str(page.url), verify=False)
    if response.status_code == 404:
        raise MonitoredUrlNotFoundError()
    response.raise_for_status()

    body_html = extract_body_html(response.text)
    md_content = html_to_markdown(body_html)

    latest_snapshot = Snapshot.objects.filter(page=page).order_by("-created_at").first()
    has_changed = latest_snapshot is None or latest_snapshot.md_content != md_content

    Snapshot.objects.create(
        page=page,
        html_content=body_html,
        md_content=md_content,
    )

    metadata = extract_metadata(response.text, str(page.url))
    page.title = metadata["title"]
    page.icon = metadata["icon"]
    page.last_checked_at = timezone.now()
    page.save(update_fields=["last_checked_at", "title", "icon"])

    return has_changed


def create_question(text: str) -> Question:
    return Question.objects.create(text=text)


def list_questions(*, max_count: int = 20) -> list[Question]:
    return list(Question.objects.order_by("-created_at")[:max_count])


def list_categories() -> list[Category]:
    return list(Category.objects.order_by("name", "id"))


def create_category(name: str) -> Category:
    """Persist category; *emoji* from Gemini suggestion for *name*."""
    emoji = gemini_service.suggest_category_emoji(name)
    return Category.objects.create(name=name, emoji=emoji)


def delete_question(question_id: int) -> None:
    Question.objects.filter(id=question_id).delete()


@transaction.atomic
def associate_questions_with_page(page_id: int, question_ids: list[int]) -> None:
    """Replace page's question links. Unknown ids omitted. Empty list clears all."""
    page = Page.objects.select_for_update().get(id=page_id)
    existing_ids = (
        list(
            Question.objects.filter(id__in=question_ids).values_list("id", flat=True)
        )
        if question_ids
        else []
    )
    page.questions.set(existing_ids)


def compare_snapshots(page_id: int, question: str, *, use_html: bool = False) -> str:
    """Answer a question about the page's snapshots using Gemini.

    Uses the two most recent snapshots when both exist; otherwise answers from
    the single latest snapshot only. *use_html* is ignored (kept for API compatibility);
    prompts always use Markdown snapshots.
    """
    page = get_page(page_id=page_id)

    snapshots = list(page.snapshots.order_by("-created_at")[:2])
    if not snapshots:
        raise ValueError("Page must have at least one snapshot to ask questions.")

    if len(snapshots) == 1:
        return gemini_service.answer_question_about_snapshot(
            snapshot_id=snapshots[0].id,
            question=question,
        )

    older, newer = snapshots[1], snapshots[0]

    return gemini_service.compare_snapshots(
        snapshot_a_id=older.id,
        snapshot_b_id=newer.id,
        question=question,
    )
