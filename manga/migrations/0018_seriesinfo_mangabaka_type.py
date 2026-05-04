# MangaBaka series ``type`` from detail API → ``SeriesInfo``.

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("manga", "0016_mangabaka_schedule_every_5m_snooze_squashed_0017_series_mangabaka_snooze_move"),
    ]

    operations = [
        migrations.AddField(
            model_name="seriesinfo",
            name="mangabaka_type",
            field=models.CharField(
                blank=True,
                default="",
                max_length=64,
                help_text="MangaBaka API ``type`` field from series detail (e.g. manga, manhwa).",
            ),
        ),
    ]
