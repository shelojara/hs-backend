# MangaBaka: cron every 5 minutes; no-match snooze field + reopen old no-match rows.

from datetime import UTC, timedelta
from zoneinfo import ZoneInfo

from django.db import migrations, models
from django.utils import timezone

SCHEDULE_NAME = "manga_mangabaka_series_info_sync"
SANTIAGO = ZoneInfo("America/Santiago")


def _next_run_in_five_minutes_from_now() -> timezone.datetime:
    now = timezone.now().astimezone(SANTIAGO)
    run = now.replace(second=0, microsecond=0)
    minute = (run.minute // 5) * 5
    run = run.replace(minute=minute)
    if run <= now:
        run += timedelta(minutes=5)
    return run.astimezone(UTC)


def _next_run_top_of_hour_santiago() -> timezone.datetime:
    now = timezone.now().astimezone(SANTIAGO)
    run = now.replace(minute=0, second=0, microsecond=0)
    if run <= now:
        run += timedelta(hours=1)
    return run.astimezone(UTC)


def update_mangabaka_schedule(apps, schema_editor):
    Schedule = apps.get_model("django_q", "Schedule")
    row = Schedule.objects.filter(name=SCHEDULE_NAME).first()
    if not row:
        return
    row.schedule_type = "C"
    row.cron = "*/5 * * * *"
    row.next_run = _next_run_in_five_minutes_from_now()
    row.save(update_fields=["schedule_type", "cron", "next_run"])


def reverse_mangabaka_schedule(apps, schema_editor):
    Schedule = apps.get_model("django_q", "Schedule")
    row = Schedule.objects.filter(name=SCHEDULE_NAME).first()
    if not row:
        return
    row.cron = "0 * * * *"
    row.next_run = _next_run_top_of_hour_santiago()
    row.save(update_fields=["cron", "next_run"])


def reopen_stuck_no_match_rows(apps, schema_editor):
    SeriesInfo = apps.get_model("manga", "SeriesInfo")
    SeriesInfo.objects.filter(is_complete=True, mangabaka_series_id__isnull=True).update(
        is_complete=False,
    )


class Migration(migrations.Migration):

    dependencies = [
        ("django_q", "0018_task_success_index"),
        ("manga", "0015_mangabaka_series_info_schedule"),
    ]

    operations = [
        migrations.AddField(
            model_name="seriesinfo",
            name="search_snoozed_until",
            field=models.DateTimeField(
                blank=True,
                db_index=True,
                help_text="After no MangaBaka title match, next search allowed at this time (UTC).",
                null=True,
            ),
        ),
        migrations.RunPython(update_mangabaka_schedule, reverse_mangabaka_schedule),
        migrations.RunPython(reopen_stuck_no_match_rows, migrations.RunPython.noop),
    ]
