# Generated manually for Google Drive OAuth (admin-managed).

from django.db import migrations, models


def _create_singleton(apps, schema_editor):
    GoogleDriveApplicationCredentials = apps.get_model("manga", "GoogleDriveApplicationCredentials")
    GoogleDriveApplicationCredentials.objects.get_or_create(pk=1)


class Migration(migrations.Migration):
    dependencies = [
        ("manga", "0023_clear_google_drive_backup_jobs_require_series_item"),
    ]

    operations = [
        migrations.CreateModel(
            name="GoogleDriveApplicationCredentials",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "client_id",
                    models.CharField(
                        blank=True,
                        default="",
                        max_length=256,
                        help_text="OAuth 2.0 Web client ID from Google Cloud Console.",
                    ),
                ),
                (
                    "client_secret",
                    models.TextField(
                        blank=True,
                        default="",
                        help_text="OAuth 2.0 client secret (stored in DB; restrict admin access).",
                    ),
                ),
                (
                    "refresh_token",
                    models.TextField(
                        blank=True,
                        default="",
                        help_text="Filled after staff completes browser OAuth (offline access).",
                    ),
                ),
                (
                    "access_token",
                    models.TextField(
                        blank=True,
                        default="",
                        help_text="Cached access token (refreshed automatically when near expiry).",
                    ),
                ),
                (
                    "access_token_expires_at",
                    models.DateTimeField(
                        null=True,
                        blank=True,
                        help_text="When access_token expires (UTC).",
                    ),
                ),
                (
                    "token_uri",
                    models.CharField(
                        default="https://oauth2.googleapis.com/token",
                        max_length=256,
                    ),
                ),
                (
                    "updated_at",
                    models.DateTimeField(auto_now=True),
                ),
            ],
            options={
                "verbose_name": "Google Drive OAuth credentials",
                "verbose_name_plural": "Google Drive OAuth credentials",
            },
        ),
        migrations.RunPython(_create_singleton, migrations.RunPython.noop),
    ]
