# Library FK on async manga jobs (convert / Drive backup / Drive restore).

import django.db.models.deletion
from django.db import migrations, models


def forwards_fill_job_library(apps, schema_editor):
    CbzConvertJob = apps.get_model("manga", "CbzConvertJob")
    GoogleDriveBackupJob = apps.get_model("manga", "GoogleDriveBackupJob")
    GoogleDriveRestoreJob = apps.get_model("manga", "GoogleDriveRestoreJob")
    Series = apps.get_model("manga", "Series")
    MangaLibrary = apps.get_model("manga", "MangaLibrary")

    for job in CbzConvertJob.objects.exclude(series_id=None).iterator(chunk_size=200):
        try:
            s = Series.objects.get(pk=job.series_id)
        except Series.DoesNotExist:
            continue
        CbzConvertJob.objects.filter(pk=job.pk).update(library_id=s.library_id)

    for job in GoogleDriveBackupJob.objects.exclude(series_id=None).iterator(chunk_size=200):
        try:
            s = Series.objects.get(pk=job.series_id)
        except Series.DoesNotExist:
            continue
        GoogleDriveBackupJob.objects.filter(pk=job.pk).update(library_id=s.library_id)

    for job in GoogleDriveRestoreJob.objects.iterator(chunk_size=200):
        lib = (
            MangaLibrary.objects.filter(filesystem_path=job.manga_root)
            .order_by("pk")
            .first()
        )
        if lib is None:
            lib = MangaLibrary.objects.order_by("pk").first()
        if lib is None:
            root = (job.manga_root or "").strip() or "/tmp"
            lib = MangaLibrary.objects.create(
                name="Default",
                filesystem_path=root,
            )
        GoogleDriveRestoreJob.objects.filter(pk=job.pk).update(library_id=lib.pk)


def backwards_clear_job_library(apps, schema_editor):
    CbzConvertJob = apps.get_model("manga", "CbzConvertJob")
    GoogleDriveBackupJob = apps.get_model("manga", "GoogleDriveBackupJob")
    GoogleDriveRestoreJob = apps.get_model("manga", "GoogleDriveRestoreJob")
    CbzConvertJob.objects.all().update(library_id=None)
    GoogleDriveBackupJob.objects.all().update(library_id=None)
    GoogleDriveRestoreJob.objects.all().update(library_id=None)


class Migration(migrations.Migration):
    dependencies = [
        ("manga", "0035_manga_library_and_series_fk"),
    ]

    operations = [
        migrations.AddField(
            model_name="cbzconvertjob",
            name="library",
            field=models.ForeignKey(
                null=True,
                blank=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="+",
                to="manga.mangalibrary",
                help_text="Manga library this convert job targets.",
            ),
        ),
        migrations.AddField(
            model_name="googledrivebackupjob",
            name="library",
            field=models.ForeignKey(
                null=True,
                blank=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="+",
                to="manga.mangalibrary",
                help_text="Manga library this backup targets.",
            ),
        ),
        migrations.AddField(
            model_name="googledriverestorejob",
            name="library",
            field=models.ForeignKey(
                null=True,
                blank=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="+",
                to="manga.mangalibrary",
                help_text="Manga library files are restored into.",
            ),
        ),
        migrations.RunPython(forwards_fill_job_library, backwards_clear_job_library),
        migrations.AlterField(
            model_name="cbzconvertjob",
            name="library",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="+",
                to="manga.mangalibrary",
                help_text="Manga library this convert job targets.",
            ),
        ),
        migrations.AlterField(
            model_name="googledrivebackupjob",
            name="library",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="+",
                to="manga.mangalibrary",
                help_text="Manga library this backup targets.",
            ),
        ),
        migrations.AlterField(
            model_name="googledriverestorejob",
            name="library",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="+",
                to="manga.mangalibrary",
                help_text="Manga library files are restored into.",
            ),
        ),
    ]
