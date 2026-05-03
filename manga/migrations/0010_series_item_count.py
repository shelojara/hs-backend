from django.db import migrations, models


def backfill_series_item_count(apps, schema_editor):
    Series = apps.get_model("manga", "Series")
    SeriesItem = apps.get_model("manga", "SeriesItem")
    for s in Series.objects.all().iterator():
        n = SeriesItem.objects.filter(series_id=s.pk).count()
        if n != s.item_count:
            s.item_count = n
            s.save(update_fields=["item_count"])


class Migration(migrations.Migration):
    dependencies = [
        ("manga", "0009_cbzconvertjob_series_not_null"),
    ]

    operations = [
        migrations.AddField(
            model_name="series",
            name="item_count",
            field=models.PositiveIntegerField(
                default=0,
                help_text="Number of cached SeriesItem rows (CBZ files) for this series; set by library sync.",
            ),
        ),
        migrations.RunPython(backfill_series_item_count, migrations.RunPython.noop),
    ]
