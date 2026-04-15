"""django-q2 scheduled and background tasks for page monitoring."""

from django_q.tasks import async_task

from pagechecker import services


def run_daily_page_check_dispatch() -> list[int]:
    """Enqueue one background task per page due for scheduled check."""
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
