"""django-q2 scheduled and background tasks for page monitoring."""

from django.conf import settings

from django_q.tasks import async_task

from pagechecker import services

EXPECTED_APP_TIME_ZONE = "America/Santiago"


def run_daily_page_check_dispatch() -> list[int]:
    """Enqueue one background task per daily-report page (only if TIME_ZONE matches)."""
    if settings.TIME_ZONE != EXPECTED_APP_TIME_ZONE:
        return []
    page_ids = services.page_ids_due_for_scheduled_check()
    for page_id in page_ids:
        async_task(
            "pagechecker.scheduled_tasks.run_scheduled_page_check",
            page_id,
            task_name=f"scheduled_page_check:{page_id}",
        )
    return page_ids


def run_scheduled_page_check(page_id: int) -> None:
    """Placeholder for per-page scheduled work (fetch/report)."""
    _ = page_id
