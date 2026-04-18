import logging
from collections.abc import Sequence

import httpx
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from backend.email_services import send_email_via_gmail
from pagechecker import gemini_service
from pagechecker.html_utils import (
    extract_body_html,
    extract_metadata,
    html_to_markdown,
)
from pagechecker.models import Category, Page, Question, ReportInterval, Snapshot

logger = logging.getLogger(__name__)


def page_ids_due_for_scheduled_check() -> list[int]:
    """All pages with *report_interval* DAILY (for daily scheduled dispatch)."""
    return list(
        Page.objects.filter(report_interval=ReportInterval.DAILY)
        .order_by("id")
        .values_list("id", flat=True)
    )


def page_ids_due_for_weekly_scheduled_check() -> list[int]:
    """All pages with *report_interval* WEEKLY (for weekly scheduled dispatch)."""
    return list(
        Page.objects.filter(report_interval=ReportInterval.WEEKLY)
        .order_by("id")
        .values_list("id", flat=True)
    )


def page_ids_due_for_monthly_scheduled_check() -> list[int]:
    """All pages with *report_interval* MONTHLY (for monthly scheduled dispatch)."""
    return list(
        Page.objects.filter(report_interval=ReportInterval.MONTHLY)
        .order_by("id")
        .values_list("id", flat=True)
    )


def send_daily_reports() -> list[int]:
    """Enqueue daily-report jobs for all pages with *report_interval* DAILY."""
    from pagechecker import scheduled_tasks

    return scheduled_tasks.enqueue_daily_report_jobs()


def send_weekly_reports() -> list[int]:
    """Enqueue weekly-report jobs for all pages with *report_interval* WEEKLY."""
    from pagechecker import scheduled_tasks

    return scheduled_tasks.enqueue_weekly_report_jobs()


def send_monthly_reports() -> list[int]:
    """Enqueue monthly-report jobs for all pages with *report_interval* MONTHLY."""
    from pagechecker import scheduled_tasks

    return scheduled_tasks.enqueue_monthly_report_jobs()


class MonitoredUrlNotFoundError(Exception):
    """Monitored URL responded with HTTP 404."""

    def __init__(self, message: str = "The monitored URL returned HTTP 404 (Not Found).") -> None:
        super().__init__(message)


class QuestionInUseError(Exception):
    """Question still linked to at least one page; delete blocked."""

    def __init__(
        self,
        message: str = "Cannot delete question while it is linked to one or more pages.",
    ) -> None:
        super().__init__(message)


def list_pages(*, user_id: int, limit: int = 20, offset: int = 0) -> list[Page]:
    qs = (
        Page.objects.filter(owner_id=user_id)
        .order_by("-created_at")
        .select_related("category", "highlighted_question")
        .prefetch_related("questions")
    )
    return list(qs[offset : offset + limit])


def get_page(page_id: int, *, user_id: int) -> Page:
    return (
        Page.objects.select_related("category", "highlighted_question")
        .prefetch_related("questions")
        .get(id=page_id, owner_id=user_id)
    )


def _categories_with_examples_for_gemini(
    *, owner_id: int, exclude_page_id: int
) -> list[dict]:
    """Category id, name, and up to 5 other pages per category (for Gemini matching)."""
    out: list[dict] = []
    for cat in Category.objects.order_by("name", "id"):
        pages = list(
            Page.objects.filter(category=cat, owner_id=owner_id)
            .exclude(id=exclude_page_id)
            .order_by("-created_at")[:5]
        )
        out.append(
            {
                "id": cat.id,
                "name": cat.name,
                "examples": [{"url": p.url, "title": p.title or ""} for p in pages],
            }
        )
    return out


def _assign_page_category_via_gemini(page: Page) -> None:
    """If categories exist, ask Gemini to pick one from URL/title + peer examples."""
    blocks = _categories_with_examples_for_gemini(
        owner_id=page.owner_id,
        exclude_page_id=page.id,
    )
    if not blocks:
        return
    try:
        category_id = gemini_service.suggest_page_category_id(
            page_url=page.url,
            page_title=page.title or "",
            categories=blocks,
        )
    except RuntimeError:
        logger.warning(
            "Skipped Gemini page category: GEMINI_API_KEY not set (page id=%s).",
            page.id,
        )
        return
    except Exception:
        logger.exception("Gemini page category failed for page id=%s", page.id)
        return
    if category_id is None:
        return
    if not Category.objects.filter(id=category_id).exists():
        logger.warning(
            "Gemini returned unknown category_id=%s for page id=%s",
            category_id,
            page.id,
        )
        return
    page.category_id = category_id
    page.save(update_fields=["category_id"])


def create_page(url: str, *, user_id: int) -> int:
    page = Page.objects.create(url=url, owner_id=user_id)
    check_page(page.id)
    page.refresh_from_db()
    _assign_page_category_via_gemini(page)
    return page.id


@transaction.atomic
def change_page_url(
    page_id: int,
    url: str,
    *,
    user_id: int,
    keep_snapshots: bool = False,
) -> None:
    """Set page URL; purge snapshots unless *keep_snapshots*.

    When URL value changes, runs *check_page* to refresh title/icon and add snapshot.
    """
    page = Page.objects.select_for_update().get(id=page_id, owner_id=user_id)
    old_url = page.url
    page.url = url
    page.save(update_fields=["url"])

    if not keep_snapshots:
        page.snapshots.all().delete()

    if old_url != url:
        check_page(page.id)


@transaction.atomic
def set_page_category(
    page_id: int, *, user_id: int, category_id: int | None = None
) -> None:
    """Set page category FK only; does not touch report interval or URL."""
    page = Page.objects.select_for_update().get(id=page_id, owner_id=user_id)
    page.category_id = category_id
    page.save(update_fields=["category_id"])


@transaction.atomic
def set_page_report_interval(
    page_id: int,
    *,
    user_id: int,
    report_interval: str | None = None,
) -> None:
    """Set *report_interval* (DAILY/WEEKLY/MONTHLY) or clear when *None*."""
    page = Page.objects.select_for_update().get(id=page_id, owner_id=user_id)
    page.report_interval = report_interval
    page.save(update_fields=["report_interval"])


@transaction.atomic
def set_page_feature_instruction(
    page_id: int,
    *,
    user_id: int,
    feature_instruction: str | None = None,
) -> None:
    """Set *feature_instruction* text or clear when *None* or blank after strip."""
    page = Page.objects.select_for_update().get(id=page_id, owner_id=user_id)
    if feature_instruction is None:
        page.feature_instruction = None
    else:
        stripped = feature_instruction.strip()
        page.feature_instruction = stripped if stripped else None
    page.save(update_fields=["feature_instruction"])


def delete_page(page_id: int, *, user_id: int) -> None:
    Page.objects.filter(id=page_id, owner_id=user_id).delete()


def check_page(page_id: int) -> bool:
    """Fetch the page, snapshot its text content, and return whether it changed."""
    page = Page.objects.get(id=page_id)

    response = httpx.get(str(page.url), verify=False)
    if response.status_code == 404:
        raise MonitoredUrlNotFoundError()
    response.raise_for_status()

    body_html = extract_body_html(response.text)
    md_content = html_to_markdown(body_html)
    metadata = extract_metadata(response.text, str(page.url))
    page_title_for_prompt = metadata["title"] or page.title or ""

    latest_snapshot = Snapshot.objects.filter(page=page).order_by("-created_at").first()
    has_changed = latest_snapshot is None or latest_snapshot.md_content != md_content

    feature_text: str | None = None
    instr = (page.feature_instruction or "").strip()
    if instr:
        now = timezone.now()
        try:
            feature_text = gemini_service.extract_snapshot_feature(
                feature_instruction=instr,
                page_url=str(page.url),
                page_title=page_title_for_prompt,
                md_content=md_content,
                old_md_content=(
                    latest_snapshot.md_content if latest_snapshot else None
                ),
                old_snapshot_taken_at=(
                    latest_snapshot.created_at if latest_snapshot else None
                ),
                new_snapshot_taken_at=now,
            )
        except RuntimeError:
            logger.warning(
                "Skipped Gemini snapshot feature: GEMINI_API_KEY not set (page id=%s).",
                page.id,
            )
        except Exception:
            logger.exception("Gemini snapshot feature failed for page id=%s", page.id)

    Snapshot.objects.create(
        page=page,
        html_content=body_html,
        md_content=md_content,
        feature=feature_text,
    )

    page.title = metadata["title"]
    page.icon = metadata["icon"]
    page.last_checked_at = timezone.now()
    page.save(update_fields=["last_checked_at", "title", "icon"])

    return has_changed


def create_question(text: str, *, user_id: int) -> Question:
    return Question.objects.create(text=text, owner_id=user_id)


def list_questions(*, user_id: int, max_count: int = 20) -> list[Question]:
    return list(
        Question.objects.filter(owner_id=user_id).order_by("-created_at")[:max_count]
    )


def list_categories() -> list[Category]:
    return list(Category.objects.order_by("name", "id"))


def create_category(name: str) -> Category:
    """Persist category; *emoji* from Gemini suggestion for *name*."""
    emoji = gemini_service.suggest_category_emoji(name)
    return Category.objects.create(name=name, emoji=emoji)


def delete_question(question_id: int, *, user_id: int) -> None:
    try:
        question = Question.objects.get(id=question_id, owner_id=user_id)
    except Question.DoesNotExist:
        return
    if question.pages.exists():
        raise QuestionInUseError()
    question.delete()


@transaction.atomic
def associate_questions_with_page(
    page_id: int, question_ids: list[int], *, user_id: int
) -> None:
    """Replace page's question links. Unknown ids omitted. Empty list clears all."""
    page = Page.objects.select_for_update().get(id=page_id, owner_id=user_id)
    existing_ids = (
        list(
            Question.objects.filter(
                id__in=question_ids,
                owner_id=user_id,
            ).values_list("id", flat=True)
        )
        if question_ids
        else []
    )
    page.questions.set(existing_ids)
    if (
        page.highlighted_question_id is not None
        and page.highlighted_question_id not in existing_ids
    ):
        page.highlighted_question_id = None
        page.save(update_fields=["highlighted_question_id"])


@transaction.atomic
def set_page_highlighted_question(
    page_id: int, question_id: int | None, *, user_id: int
) -> None:
    """Set which linked question UI should emphasize; *None* clears."""
    page = Page.objects.select_for_update().get(id=page_id, owner_id=user_id)
    if question_id is None:
        page.highlighted_question_id = None
        page.save(update_fields=["highlighted_question_id"])
        return
    if not page.questions.filter(id=question_id).exists():
        msg = "Question is not linked to this page."
        raise ValueError(msg)
    exists = Question.objects.filter(id=question_id, owner_id=user_id).exists()
    if not exists:
        msg = "Question not found."
        raise ValueError(msg)
    page.highlighted_question_id = question_id
    page.save(update_fields=["highlighted_question_id"])


def compare_snapshots(
    page_id: int, question: str, *, user_id: int, use_html: bool = False
) -> str:
    """Answer a question about the page's snapshots using Gemini.

    Uses the two most recent snapshots when both exist; otherwise answers from
    the single latest snapshot only. *use_html* is ignored (kept for API compatibility);
    prompts always use Markdown snapshots.
    """
    page = get_page(page_id=page_id, user_id=user_id)

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


def _report_recipient_emails_for_user(user_id: int) -> list[str]:
    """Distinct non-blank emails for *user_id* when user active (order stable)."""
    User = get_user_model()
    ordered: list[str] = []
    seen: set[str] = set()
    qs = (
        User.objects.filter(pk=user_id, is_active=True)
        .exclude(email__isnull=True)
        .exclude(email="")
        .order_by("id")
        .values_list("email", flat=True)
    )
    for raw in qs:
        addr = str(raw).strip()
        if addr and addr not in seen:
            seen.add(addr)
            ordered.append(addr)
    return ordered


def run_daily_report_for_page(page_id: int) -> None:
    """Fetch page, answer all linked questions via Gemini, email plain-text report.

    Runs even when content unchanged. Recipients: page owner's non-blank email
    when owner is active. Skips mail when that list is empty.
    """
    try:
        page = Page.objects.prefetch_related("questions").get(id=page_id)
    except Page.DoesNotExist:
        logger.warning("Daily report skipped: page id=%s does not exist.", page_id)
        return

    check_error: str | None = None
    has_changed: bool | None = None
    try:
        has_changed = check_page(page_id)
    except Exception as exc:
        check_error = str(exc)
        logger.exception("Daily report check_page failed for page id=%s", page_id)

    page.refresh_from_db()
    page_questions: Sequence[Question] = list(page.questions.all())

    qa_lines: list[str] = []
    owner_id = page.owner_id
    for q in page_questions:
        try:
            answer = compare_snapshots(page_id, q.text, user_id=owner_id)
        except Exception as exc:
            qa_lines.append(f"Q: {q.text}\nError: {exc}")
            logger.exception(
                "Daily report question failed page id=%s question id=%s",
                page_id,
                q.id,
            )
        else:
            qa_lines.append(f"Q: {q.text}\nA: {answer}")

    if has_changed is None:
        status_line = f"Check: failed — {check_error}"
    elif has_changed:
        status_line = "Check: succeeded — content changed since previous snapshot."
    else:
        status_line = "Check: succeeded — no content change since previous snapshot."

    latest = page.latest_snapshot
    feature_text = (latest.feature or "").strip() if latest else ""

    body_parts = [
        "Page Checker — daily report",
        "",
        f"URL: {page.url}",
        f"Title: {page.title or '(none)'}",
        "",
        status_line,
    ]
    if feature_text:
        body_parts.extend(["", f"Snapshot feature: {feature_text}"])
    body_parts.extend(
        [
            "",
            "Questions",
            "-------",
        ]
    )
    if qa_lines:
        body_parts.append("\n\n".join(qa_lines))
    else:
        body_parts.append("(no questions linked to this page)")

    body = "\n".join(body_parts)

    recipients = _report_recipient_emails_for_user(owner_id)
    if not recipients:
        logger.warning(
            "Daily report for page id=%s not emailed: owner has no email or inactive.",
            page_id,
        )
        return

    label = page.title.strip() or page.url
    subject = f"Page Checker daily report: {label}"

    try:
        send_email_via_gmail(to_addrs=recipients, subject=subject, body=body)
    except Exception:
        logger.exception("Daily report email send failed for page id=%s", page_id)
