# Switch dispatcher to cron 9:00 America/Santiago (django TIME_ZONE).

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


def set_cron_9am(apps, schema_editor):
    Schedule = apps.get_model("django_q", "Schedule")
    Schedule.objects.filter(name=SCHEDULE_NAME).update(
        schedule_type="C",
        cron="0 9 * * *",
        next_run=_next_run_9am_santiago(),
    )


def revert_to_daily(apps, schema_editor):
    Schedule = apps.get_model("django_q", "Schedule")
    Schedule.objects.filter(name=SCHEDULE_NAME).update(
        schedule_type="D",
        cron="",
        next_run=timezone.now(),
    )


class Migration(migrations.Migration):
    dependencies = [
        ("pagechecker", "0017_daily_page_check_schedule"),
    ]

    operations = [
        migrations.RunPython(set_cron_9am, revert_to_daily),
    ]
