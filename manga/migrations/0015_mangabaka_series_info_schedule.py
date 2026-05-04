# django-q2: hourly MangaBaka series metadata sync (small batches per run).

from datetime import UTC, timedelta
from zoneinfo import ZoneInfo

from django.db import migrations
from django.utils import timezone

SCHEDULE_NAME = "manga_mangabaka_series_info_sync"
SANTIAGO = ZoneInfo("America/Santiago")


def _next_run_top_of_hour_santiago() -> timezone.datetime:
    now = timezone.now().astimezone(SANTIAGO)
    run = now.replace(minute=0, second=0, microsecond=0)
    if run <= now:
        run += timedelta(hours=1)
    return run.astimezone(UTC)


def create_schedule(apps, schema_editor):
    Schedule = apps.get_model("django_q", "Schedule")
    if Schedule.objects.filter(name=SCHEDULE_NAME).exists():
        return
    Schedule.objects.create(
        name=SCHEDULE_NAME,
        func="manga.scheduled_tasks.run_manga_mangabaka_series_info_sync",
        schedule_type="C",
        cron="0 * * * *",
        repeats=-1,
        next_run=_next_run_top_of_hour_santiago(),
    )


def remove_schedule(apps, schema_editor):
    Schedule = apps.get_model("django_q", "Schedule")
    Schedule.objects.filter(name=SCHEDULE_NAME).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("django_q", "0018_task_success_index"),
        ("manga", "0014_seriesinfo"),
    ]

    operations = [
        migrations.RunPython(create_schedule, remove_schedule),
    ]
