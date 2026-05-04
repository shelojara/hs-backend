from django.db import migrations, models


def backfill_google_drive_backed_up(apps, schema_editor):
    GoogleDriveBackupJob = apps.get_model("manga", "GoogleDriveBackupJob")
    SeriesItem = apps.get_model("manga", "SeriesItem")
    completed = GoogleDriveBackupJob.objects.filter(status="completed").values_list(
        "series_item_id", flat=True
    )
    SeriesItem.objects.filter(pk__in=completed).update(is_google_drive_backed_up=True)


class Migration(migrations.Migration):
    dependencies = [
        ("manga", "0025_rename_seriesitem_in_dropbox_is_converted"),
    ]

    operations = [
        migrations.AddField(
            model_name="seriesitem",
            name="is_google_drive_backed_up",
            field=models.BooleanField(
                db_index=True,
                default=False,
                help_text=(
                    "True after a Google Drive backup job completed for this file "
                    "(upload or same-name+size skip)."
                ),
            ),
        ),
        migrations.RunPython(backfill_google_drive_backed_up, migrations.RunPython.noop),
    ]
