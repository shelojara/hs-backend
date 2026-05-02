# django-q2: refresh manga library DB cache every 5 minutes (TIME_ZONE).

from datetime import UTC, timedelta
from zoneinfo import ZoneInfo

from django.db import migrations
from django.utils import timezone

SCHEDULE_NAME = "manga_library_cache_refresh"
SANTIAGO = ZoneInfo("America/Santiago")


def _next_run_in_five_minutes_from_now() -> timezone.datetime:
    now = timezone.now().astimezone(SANTIAGO)
    run = now.replace(second=0, microsecond=0)
    minute = (run.minute // 5) * 5
    run = run.replace(minute=minute)
    if run <= now:
        run += timedelta(minutes=5)
    return run.astimezone(UTC)


def create_schedule(apps, schema_editor):
    Schedule = apps.get_model("django_q", "Schedule")
    if Schedule.objects.filter(name=SCHEDULE_NAME).exists():
        return
    Schedule.objects.create(
        name=SCHEDULE_NAME,
        func="manga.scheduled_tasks.run_manga_library_cache_refresh",
        schedule_type="C",
        cron="*/5 * * * *",
        repeats=-1,
        next_run=_next_run_in_five_minutes_from_now(),
    )


def remove_schedule(apps, schema_editor):
    Schedule = apps.get_model("django_q", "Schedule")
    Schedule.objects.filter(name=SCHEDULE_NAME).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("django_q", "0018_task_success_index"),
        ("manga", "0002_manga_library_cache_models"),
    ]

    operations = [
        migrations.RunPython(create_schedule, remove_schedule),
    ]
