from django.db import migrations, models


def backfill_series_converted_item_count(apps, schema_editor):
    Series = apps.get_model("manga", "Series")
    SeriesItem = apps.get_model("manga", "SeriesItem")
    for s in Series.objects.all().iterator():
        n = SeriesItem.objects.filter(series_id=s.pk, in_dropbox=True).count()
        if n != s.converted_item_count:
            s.converted_item_count = n
            s.save(update_fields=["converted_item_count"])


class Migration(migrations.Migration):
    dependencies = [
        ("manga", "0016_mangabaka_schedule_every_5m_snooze_squashed_0017_series_mangabaka_snooze_move"),
    ]

    operations = [
        migrations.AddField(
            model_name="series",
            name="converted_item_count",
            field=models.PositiveIntegerField(
                default=0,
                help_text=(
                    "Number of SeriesItem rows with in_dropbox=true "
                    "(converted / present in Dropbox cache)."
                ),
            ),
        ),
        migrations.RunPython(backfill_series_converted_item_count, migrations.RunPython.noop),
    ]
