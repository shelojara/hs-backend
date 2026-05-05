# Generated manually for Google Drive series restore from backup.

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("manga", "0027_rename_seriesitem_is_google_drive_backed_up_is_backed_up"),
    ]

    operations = [
        migrations.CreateModel(
            name="GoogleDriveRestoreJob",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "manga_root",
                    models.CharField(
                        help_text="Normalized absolute manga library root when job was created.",
                        max_length=4096,
                    ),
                ),
                (
                    "series_name",
                    models.CharField(
                        help_text="Series folder name under Drive ``Manga/<name>/`` (matches backup layout).",
                        max_length=1024,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("completed", "Completed"),
                            ("failed", "Failed"),
                        ],
                        db_index=True,
                        default="pending",
                        max_length=16,
                    ),
                ),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("failure_message", models.TextField(blank=True, null=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=models.CASCADE,
                        related_name="manga_google_drive_restore_jobs",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ("-created_at", "-id"),
            },
        ),
        migrations.AddIndex(
            model_name="googledriverestorejob",
            index=models.Index(fields=["user_id", "manga_root"], name="manga_gdrive_restore_user_root"),
        ),
    ]
