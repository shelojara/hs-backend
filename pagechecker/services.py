import httpx
from django.db import transaction
from django.utils import timezone

from pagechecker import gemini_service
from pagechecker.html_utils import (
    extract_body_html,
    extract_metadata,
    html_to_markdown,
)
from pagechecker.models import Page, Question, Snapshot


def list_pages(limit: int = 20, offset: int = 0) -> list[Page]:
    qs = Page.objects.order_by("-created_at").prefetch_related("questions")
    return list(qs[offset : offset + limit])


def get_page(page_id: int) -> Page:
    return Page.objects.prefetch_related("questions").get(id=page_id)


def create_page(url: str) -> int:
    page = Page.objects.create(url=url)
    check_page(page.id)
    return page.id


@transaction.atomic
def update_page(page_id: int, url: str, *, keep_snapshots: bool = False) -> None:
    """Update a page's URL, re-extract title/icon, and optionally clear old snapshots."""
    page = Page.objects.select_for_update().get(id=page_id)
    page.url = url
    page.save(update_fields=["url"])

    if not keep_snapshots:
        page.snapshots.all().delete()

    check_page(page.id)


def delete_page(page_id: int) -> None:
    Page.objects.filter(id=page_id).delete()


def check_page(page_id: int) -> bool:
    """Fetch the page, snapshot its text content, and return whether it changed."""
    page = Page.objects.get(id=page_id)

    response = httpx.get(str(page.url), verify=False)
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
