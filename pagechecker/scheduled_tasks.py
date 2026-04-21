"""django-q2 scheduled and background tasks for page monitoring."""

from django_q.tasks import async_task

from pagechecker import services


def enqueue_daily_report_jobs() -> list[int]:
    """Enqueue one background task per page with report_interval DAILY."""
    page_ids = services.page_ids_due_for_scheduled_check()
    for page_id in page_ids:
        async_task(
            "pagechecker.scheduled_tasks.run_scheduled_page_check",
            page_id,
            task_name=f"scheduled_page_check:{page_id}",
        )
    return page_ids


def enqueue_weekly_report_jobs() -> list[int]:
    """Enqueue one background task per page with report_interval WEEKLY."""
    page_ids = services.page_ids_due_for_weekly_scheduled_check()
    for page_id in page_ids:
        async_task(
            "pagechecker.scheduled_tasks.run_scheduled_page_check",
            page_id,
            task_name=f"scheduled_weekly_page_check:{page_id}",
        )
    return page_ids


def enqueue_monthly_report_jobs() -> list[int]:
    """Enqueue one background task per page with report_interval MONTHLY."""
    page_ids = services.page_ids_due_for_monthly_scheduled_check()
    for page_id in page_ids:
        async_task(
            "pagechecker.scheduled_tasks.run_scheduled_page_check",
            page_id,
            task_name=f"scheduled_monthly_page_check:{page_id}",
        )
    return page_ids


def run_daily_page_check_dispatch() -> list[int]:
    """Enqueue one background task per page with report_interval DAILY."""
    return enqueue_daily_report_jobs()


def run_weekly_page_check_dispatch() -> list[int]:
    """Enqueue one background task per page with report_interval WEEKLY."""
    return enqueue_weekly_report_jobs()


def run_monthly_page_check_dispatch() -> list[int]:
    """Enqueue one background task per page with report_interval MONTHLY."""
    return enqueue_monthly_report_jobs()


def run_scheduled_page_check(page_id: int) -> None:
    """Daily job: fetch page, run all linked questions, email report."""
    services.run_daily_report_for_page(page_id)


def enqueue_search_job(search_id: int) -> None:
    async_task(
        "pagechecker.scheduled_tasks.run_search_job",
        search_id,
        task_name=f"pagechecker.search:{search_id}",
    )


def run_search_job(search_id: int) -> None:
    """Background worker: Gemini search + persist ``Search`` row."""
    services.run_search_background(search_id)
