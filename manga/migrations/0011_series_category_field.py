import posixpath

from django.db import migrations, models


def backfill_series_category(apps, schema_editor):
    Series = apps.get_model("manga", "Series")
    for row in Series.objects.all().iterator(chunk_size=500):
        parent = posixpath.dirname(row.series_rel_path)
        cat = posixpath.basename(parent) if parent else ""
        if row.category != cat:
            Series.objects.filter(pk=row.pk).update(category=cat)


class Migration(migrations.Migration):
    dependencies = [
        ("manga", "0010_series_item_count"),
    ]

    operations = [
        migrations.AddField(
            model_name="series",
            name="category",
            field=models.CharField(
                blank=True,
                db_index=True,
                default="",
                help_text="Parent directory under library root (basename of dirname(series_rel_path)); empty at root.",
                max_length=1024,
            ),
        ),
        migrations.RunPython(backfill_series_category, migrations.RunPython.noop),
        migrations.AddIndex(
            model_name="series",
            index=models.Index(
                fields=["library_root", "category"],
                name="manga_series_root_category",
            ),
        ),
        migrations.AlterField(
            model_name="series",
            name="category",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Parent directory under library root (basename of dirname(series_rel_path)); empty at root.",
                max_length=1024,
            ),
        ),
    ]
