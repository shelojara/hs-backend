# One refetch so MangaBaka ``type`` backfills for rows synced before ``mangabaka_type`` existed.

from django.db import migrations


def mark_complete_for_type_refetch(apps, schema_editor):
    SeriesInfo = apps.get_model("manga", "SeriesInfo")
    SeriesInfo.objects.filter(
        is_complete=True,
        mangabaka_series_id__isnull=False,
        mangabaka_type="",
    ).update(is_complete=False)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("manga", "0018_seriesinfo_mangabaka_type"),
    ]

    operations = [
        migrations.RunPython(mark_complete_for_type_refetch, noop),
    ]
