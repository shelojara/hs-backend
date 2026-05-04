# MangaBaka metadata row per cached Series (description, rating).

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("manga", "0013_seriesitem_dropbox_uploaded_at"),
    ]

    operations = [
        migrations.CreateModel(
            name="SeriesInfo",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "mangabaka_series_id",
                    models.PositiveIntegerField(
                        blank=True,
                        null=True,
                        help_text="MangaBaka API series id when a confident title match was found.",
                    ),
                ),
                ("description", models.TextField(blank=True, default="")),
                (
                    "rating",
                    models.IntegerField(
                        blank=True,
                        null=True,
                        help_text="Raw MangaBaka ``rating`` field (see API docs).",
                    ),
                ),
                (
                    "is_complete",
                    models.BooleanField(
                        default=False,
                        db_index=True,
                        help_text="When true, scheduled sync skips this series (match succeeded or search exhausted).",
                    ),
                ),
                (
                    "synced_at",
                    models.DateTimeField(
                        blank=True,
                        null=True,
                        help_text="When description/rating was last written or a definitive no-match was recorded.",
                    ),
                ),
                (
                    "series",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="series_info",
                        to="manga.series",
                    ),
                ),
            ],
            options={
                "verbose_name": "manga series info (MangaBaka)",
                "verbose_name_plural": "manga series info (MangaBaka)",
            },
        ),
    ]
