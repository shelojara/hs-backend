# Generated manually: async CBZ conversion jobs (django-q2), groceries Search pattern.

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("manga", "0005_series_cover_base64"),
    ]

    operations = [
        migrations.CreateModel(
            name="CbzConvertJob",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "manga_root",
                    models.CharField(
                        max_length=4096,
                        help_text="Normalized absolute manga library root when job was created.",
                    ),
                ),
                (
                    "series_item_id",
                    models.PositiveIntegerField(
                        help_text="Primary key of manga.SeriesItem to convert.",
                    ),
                ),
                (
                    "kind",
                    models.CharField(
                        max_length=16,
                        choices=[("manga", "Manga"), ("manhwa", "Manhwa")],
                        default="manga",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "status",
                    models.CharField(
                        max_length=16,
                        choices=[
                            ("pending", "Pending"),
                            ("completed", "Completed"),
                            ("failed", "Failed"),
                        ],
                        default="pending",
                        db_index=True,
                    ),
                ),
                ("completed_at", models.DateTimeField(null=True, blank=True)),
                ("failure_message", models.TextField(null=True, blank=True)),
                ("deleted_at", models.DateTimeField(null=True, blank=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=models.CASCADE,
                        related_name="manga_cbz_convert_jobs",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ("-created_at", "-id"),
                "base_manager_name": "all_objects",
                "default_manager_name": "objects",
            },
        ),
    ]
