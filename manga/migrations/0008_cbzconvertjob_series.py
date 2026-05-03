from django.db import migrations, models
import django.db.models.deletion


def backfill_job_series(apps, schema_editor):
    CbzConvertJob = apps.get_model("manga", "CbzConvertJob")
    SeriesItem = apps.get_model("manga", "SeriesItem")
    for job in CbzConvertJob.objects.filter(series__isnull=True).iterator(chunk_size=500):
        sid = (
            SeriesItem.objects.filter(pk=job.series_item_id)
            .values_list("series_id", flat=True)
            .first()
        )
        if sid is not None:
            CbzConvertJob.objects.filter(pk=job.pk).update(series_id=sid)


class Migration(migrations.Migration):
    dependencies = [
        ("manga", "0007_seriesitem_cover_base64"),
    ]

    operations = [
        migrations.AddField(
            model_name="cbzconvertjob",
            name="series",
            field=models.ForeignKey(
                blank=True,
                help_text="Series containing series_item_id; denormalized for efficient job listing.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="cbz_convert_jobs",
                to="manga.series",
            ),
        ),
        migrations.RunPython(backfill_job_series, migrations.RunPython.noop),
        migrations.AddIndex(
            model_name="cbzconvertjob",
            index=models.Index(
                fields=["user_id", "manga_root", "series_id"],
                name="manga_cbzjob_user_root_series",
            ),
        ),
    ]
