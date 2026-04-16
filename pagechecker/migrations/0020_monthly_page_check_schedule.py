# django-q2 dispatcher: cron 5th of month 10:00 America/Santiago (align with settings.TIME_ZONE).

from datetime import UTC

from zoneinfo import ZoneInfo

from django.db import migrations
from django.utils import timezone

SCHEDULE_NAME = "monthly_page_check_dispatcher"
SANTIAGO = ZoneInfo("America/Santiago")


def _next_run_5th_10am_santiago() -> timezone.datetime:
    now_local = timezone.now().astimezone(SANTIAGO)
    candidate = now_local.replace(day=5, hour=10, minute=0, second=0, microsecond=0)
    if candidate > now_local:
        return candidate.astimezone(UTC)
    y, m = now_local.year, now_local.month
    if m == 12:
        y, m = y + 1, 1
    else:
        m += 1
    candidate = now_local.replace(
        year=y, month=m, day=5, hour=10, minute=0, second=0, microsecond=0
    )
    return candidate.astimezone(UTC)


def create_monthly_schedule(apps, schema_editor):
    Schedule = apps.get_model("django_q", "Schedule")
    if Schedule.objects.filter(name=SCHEDULE_NAME).exists():
        return
    Schedule.objects.create(
        name=SCHEDULE_NAME,
        func="pagechecker.scheduled_tasks.run_monthly_page_check_dispatch",
        schedule_type="C",
        cron="0 10 5 * *",
        repeats=-1,
        next_run=_next_run_5th_10am_santiago(),
    )


def remove_monthly_schedule(apps, schema_editor):
    Schedule = apps.get_model("django_q", "Schedule")
    Schedule.objects.filter(name=SCHEDULE_NAME).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("django_q", "0018_task_success_index"),
        ("pagechecker", "0019_weekly_page_check_schedule"),
    ]

    operations = [
        migrations.RunPython(create_monthly_schedule, remove_monthly_schedule),
    ]
