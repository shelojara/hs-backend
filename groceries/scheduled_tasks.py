"""django-q2 tasks for groceries (running-low sync)."""

from django_q.tasks import async_task

from groceries import services


def run_running_low_sync_for_user(user_id: int) -> None:
    """Background job: sync ``Product.running_low`` for one user."""
    services.sync_running_low_flags_for_user(user_id=user_id)


def run_daily_running_low_sync() -> list[int]:
    """Enqueue one background task per user with products (scheduled once per day)."""
    user_ids = services.running_low_sync_user_ids()
    for uid in user_ids:
        async_task(
            "groceries.scheduled_tasks.run_running_low_sync_for_user",
            uid,
            task_name=f"groceries_running_low_sync:{uid}",
        )
    return user_ids
