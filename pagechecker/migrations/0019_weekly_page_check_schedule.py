# django-q2 dispatcher: cron Fri 9:30 America/Santiago (align with settings.TIME_ZONE).

from datetime import UTC, timedelta
from zoneinfo import ZoneInfo

from django.db import migrations
from django.utils import timezone

SCHEDULE_NAME = "weekly_page_check_dispatcher"
SANTIAGO = ZoneInfo("America/Santiago")


def _next_run_friday_930_santiago() -> timezone.datetime:
    now_local = timezone.now().astimezone(SANTIAGO)
    # Monday=0 .. Sunday=6; Friday=4
    days_ahead = (4 - now_local.weekday()) % 7
    run_local = (now_local + timedelta(days=days_ahead)).replace(
        hour=9, minute=30, second=0, microsecond=0
    )
    if run_local <= now_local:
        run_local += timedelta(weeks=1)
    return run_local.astimezone(UTC)


def create_weekly_schedule(apps, schema_editor):
    Schedule = apps.get_model("django_q", "Schedule")
    if Schedule.objects.filter(name=SCHEDULE_NAME).exists():
        return
    Schedule.objects.create(
        name=SCHEDULE_NAME,
        func="pagechecker.scheduled_tasks.run_weekly_page_check_dispatch",
        schedule_type="C",
        cron="30 9 * * 5",
        repeats=-1,
        next_run=_next_run_friday_930_santiago(),
    )


def remove_weekly_schedule(apps, schema_editor):
    Schedule = apps.get_model("django_q", "Schedule")
    Schedule.objects.filter(name=SCHEDULE_NAME).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("django_q", "0018_task_success_index"),
        ("pagechecker", "0018_page_report_interval"),
    ]

    operations = [
        migrations.RunPython(create_weekly_schedule, remove_weekly_schedule),
    ]
