"""django-q2 tasks for groceries (running-low sync)."""

from groceries import services


def run_daily_running_low_sync() -> int:
    """Update ``Product.running_low`` for all users (scheduled once per day)."""
    return services.sync_running_low_flags_for_all_users()
