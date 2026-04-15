# django-q2 dispatcher: cron 9:00 America/Santiago (align with settings.TIME_ZONE).

from datetime import UTC, timedelta
from zoneinfo import ZoneInfo

from django.db import migrations
from django.utils import timezone

SCHEDULE_NAME = "daily_page_check_dispatcher"
SANTIAGO = ZoneInfo("America/Santiago")


def _next_run_9am_santiago() -> timezone.datetime:
    now_local = timezone.now().astimezone(SANTIAGO)
    run_local = now_local.replace(hour=9, minute=0, second=0, microsecond=0)
    if run_local <= now_local:
        run_local += timedelta(days=1)
    return run_local.astimezone(UTC)


def create_daily_schedule(apps, schema_editor):
    Schedule = apps.get_model("django_q", "Schedule")
    if Schedule.objects.filter(name=SCHEDULE_NAME).exists():
        return
    Schedule.objects.create(
        name=SCHEDULE_NAME,
        func="pagechecker.scheduled_tasks.run_daily_page_check_dispatch",
        schedule_type="C",
        cron="0 9 * * *",
        repeats=-1,
        next_run=_next_run_9am_santiago(),
    )


def remove_daily_schedule(apps, schema_editor):
    Schedule = apps.get_model("django_q", "Schedule")
    Schedule.objects.filter(name=SCHEDULE_NAME).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("django_q", "0018_task_success_index"),
        ("pagechecker", "0016_page_should_report_daily"),
    ]

    operations = [
        migrations.RunPython(create_daily_schedule, remove_daily_schedule),
    ]
