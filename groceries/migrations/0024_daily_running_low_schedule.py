# django-q2: daily running-low sync (same local 9:00 as pagechecker daily dispatcher).

from datetime import UTC, timedelta
from zoneinfo import ZoneInfo

from django.db import migrations
from django.utils import timezone

SCHEDULE_NAME = "groceries_daily_running_low_sync"
SANTIAGO = ZoneInfo("America/Santiago")


def _next_run_9am_santiago() -> timezone.datetime:
    now_local = timezone.now().astimezone(SANTIAGO)
    run_local = now_local.replace(hour=9, minute=0, second=0, microsecond=0)
    if run_local <= now_local:
        run_local += timedelta(days=1)
    return run_local.astimezone(UTC)


def create_schedule(apps, schema_editor):
    Schedule = apps.get_model("django_q", "Schedule")
    if Schedule.objects.filter(name=SCHEDULE_NAME).exists():
        return
    Schedule.objects.create(
        name=SCHEDULE_NAME,
        func="groceries.scheduled_tasks.run_daily_running_low_sync",
        schedule_type="C",
        cron="0 9 * * *",
        repeats=-1,
        next_run=_next_run_9am_santiago(),
    )


def remove_schedule(apps, schema_editor):
    Schedule = apps.get_model("django_q", "Schedule")
    Schedule.objects.filter(name=SCHEDULE_NAME).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("django_q", "0018_task_success_index"),
        ("groceries", "0023_product_running_low"),
    ]

    operations = [
        migrations.RunPython(create_schedule, remove_schedule),
    ]
