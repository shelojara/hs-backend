# Squashes 0015_mangabaka_series_info_schedule + 0016_mangabaka_schedule_every_5m_snooze
# + 0017_series_mangabaka_snooze_move into one migration (same final DB state).

from datetime import UTC, timedelta
from zoneinfo import ZoneInfo

from django.db import migrations, models
from django.utils import timezone

SCHEDULE_NAME = "manga_mangabaka_series_info_sync"
SANTIAGO = ZoneInfo("America/Santiago")


def _next_run_top_of_hour_santiago() -> timezone.datetime:
    now = timezone.now().astimezone(SANTIAGO)
    run = now.replace(minute=0, second=0, microsecond=0)
    if run <= now:
        run += timedelta(hours=1)
    return run.astimezone(UTC)


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
        func="manga.scheduled_tasks.run_manga_mangabaka_series_info_sync",
        schedule_type="C",
        cron="0 * * * *",
        repeats=-1,
        next_run=_next_run_top_of_hour_santiago(),
    )


def remove_schedule(apps, schema_editor):
    Schedule = apps.get_model("django_q", "Schedule")
    Schedule.objects.filter(name=SCHEDULE_NAME).delete()


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


def copy_snooze_to_series(apps, schema_editor):
    Series = apps.get_model("manga", "Series")
    SeriesInfo = apps.get_model("manga", "SeriesInfo")
    for row in SeriesInfo.objects.exclude(search_snoozed_until__isnull=True).iterator():
        until = row.search_snoozed_until
        s = Series.objects.get(pk=row.series_id)
        if s.mangabaka_search_snoozed_until is None or until > s.mangabaka_search_snoozed_until:
            Series.objects.filter(pk=s.pk).update(mangabaka_search_snoozed_until=until)


def delete_seriesinfo_without_mangabaka_id(apps, schema_editor):
    SeriesInfo = apps.get_model("manga", "SeriesInfo")
    SeriesInfo.objects.filter(mangabaka_series_id__isnull=True).delete()


class Migration(migrations.Migration):
    replaces = [
        ("manga", "0015_mangabaka_series_info_schedule"),
        ("manga", "0016_mangabaka_schedule_every_5m_snooze"),
        ("manga", "0017_series_mangabaka_snooze_move"),
    ]

    dependencies = [
        ("django_q", "0018_task_success_index"),
        ("manga", "0014_seriesinfo"),
    ]

    operations = [
        migrations.RunPython(create_schedule, remove_schedule),
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
        migrations.AddField(
            model_name="series",
            name="mangabaka_search_snoozed_until",
            field=models.DateTimeField(
                blank=True,
                db_index=True,
                help_text=(
                    "After MangaBaka title search found no confident match, next search allowed at "
                    "this time (UTC)."
                ),
                null=True,
            ),
        ),
        migrations.RunPython(copy_snooze_to_series, migrations.RunPython.noop),
        migrations.RunPython(delete_seriesinfo_without_mangabaka_id, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="seriesinfo",
            name="search_snoozed_until",
        ),
    ]
