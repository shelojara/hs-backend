"""django-q2 scheduled and background tasks for page monitoring."""

from django_q.tasks import async_task

from pagechecker import services


def enqueue_scheduled_daily_check_jobs() -> list[int]:
    """Enqueue one background task per DAILY *report_interval* page."""
    page_ids = services.page_ids_due_for_scheduled_check()
    for page_id in page_ids:
        async_task(
            "pagechecker.scheduled_tasks.run_scheduled_page_check",
            page_id,
            task_name=f"scheduled_page_check:{page_id}",
        )
    return page_ids


def run_daily_page_check_dispatch() -> list[int]:
    """Cron entry: enqueue snapshot checks for all DAILY-interval pages."""
    return enqueue_scheduled_daily_check_jobs()


def run_scheduled_page_check(page_id: int) -> None:
    """Daily job: fetch page and snapshot (same as manual CheckPage)."""
    services.check_page(page_id)
