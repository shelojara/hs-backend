import httpx
from bs4 import BeautifulSoup
from django.utils import timezone

from pagechecker.models import Page, Snapshot


def list_pages(limit: int = 20, offset: int = 0) -> list[Page]:
    return list(Page.objects.order_by("-created_at")[offset : offset + limit])


def get_page(page_id: int) -> Page:
    return Page.objects.get(id=page_id)


def create_page(url: str) -> Page:
    page = Page.objects.create(url=url)
    check_page(page.id)
    page.refresh_from_db()
    return page


def delete_page(page_id: int) -> None:
    Page.objects.filter(id=page_id).delete()


def check_page(page_id: int) -> bool:
    """Fetch the page, snapshot its text content, and return whether it changed."""
    page = Page.objects.get(id=page_id)

    response = httpx.get(str(page.url), verify=False)
    response.raise_for_status()
    current_text = _extract_body_text(response.text)

    latest_snapshot = Snapshot.objects.filter(page=page).order_by("-created_at").first()
    has_changed = latest_snapshot is None or latest_snapshot.content != current_text

    Snapshot.objects.create(page=page, content=current_text)

    page.last_checked_at = timezone.now()
    page.save(update_fields=["last_checked_at"])

    return has_changed


def compare_snapshots(page_id: int, question: str) -> str:
    """Compare the latest two snapshots of a page using Gemini."""
    from pagechecker import gemini_service

    page = get_page(page_id=page_id)

    snapshots = list(page.snapshots.order_by("-created_at")[:2])
    if len(snapshots) < 2:
        raise ValueError("Page must have at least 2 snapshots to compare.")

    older, newer = snapshots[1], snapshots[0]

    return gemini_service.compare_snapshots(
        snapshot_a_id=older.id,
        snapshot_b_id=newer.id,
        question=question,
    )


def _extract_body_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    body = soup.body or soup

    for tag in body.find_all(["script", "style"]):
        tag.decompose()

    return body.get_text(separator="\n", strip=True)
