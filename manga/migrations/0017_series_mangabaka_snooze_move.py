# Move MangaBaka search snooze from SeriesInfo to Series; drop orphan SeriesInfo rows.

from django.db import migrations, models


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

    dependencies = [
        ("manga", "0016_mangabaka_schedule_every_5m_snooze"),
    ]

    operations = [
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
