from django.db import migrations, models
import django.db.models.deletion


def delete_jobs_missing_series(apps, schema_editor):
    CbzConvertJob = apps.get_model("manga", "CbzConvertJob")
    CbzConvertJob.objects.filter(series__isnull=True).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("manga", "0008_cbzconvertjob_series"),
    ]

    operations = [
        migrations.RunPython(delete_jobs_missing_series, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="cbzconvertjob",
            name="series",
            field=models.ForeignKey(
                help_text="Series containing series_item_id; denormalized for efficient job listing.",
                on_delete=django.db.models.deletion.PROTECT,
                related_name="cbz_convert_jobs",
                to="manga.series",
            ),
        ),
    ]
