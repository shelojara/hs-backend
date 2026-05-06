import os

from django.db import migrations, models


def backfill_series_library(apps, schema_editor):
    Series = apps.get_model("manga", "Series")
    MangaLibrary = apps.get_model("manga", "MangaLibrary")
    for s in Series.objects.all().iterator():
        root = (s.library_root or "").strip()
        if not root:
            continue
        norm = os.path.abspath(os.path.expanduser(root))
        lib = MangaLibrary.objects.filter(fs_path=norm).first()
        if lib is None:
            lib = MangaLibrary.objects.create(
                name=os.path.basename(norm)[:256] or "Library",
                fs_path=norm,
            )
        s.library_id = lib.pk
        s.save(update_fields=["library_id"])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("manga", "0035_mangalibrary"),
    ]

    operations = [
        migrations.AddField(
            model_name="series",
            name="library",
            field=models.ForeignKey(
                null=True,
                blank=True,
                on_delete=models.PROTECT,
                related_name="series",
                to="manga.mangalibrary",
            ),
        ),
        migrations.RunPython(backfill_series_library, noop_reverse),
        migrations.AlterField(
            model_name="series",
            name="library",
            field=models.ForeignKey(
                on_delete=models.PROTECT,
                related_name="series",
                to="manga.mangalibrary",
            ),
        ),
        migrations.RemoveConstraint(
            model_name="series",
            name="manga_mangalibraryseries_unique_root_path",
        ),
        migrations.RemoveIndex(
            model_name="series",
            name="manga_series_root_category",
        ),
        migrations.AddConstraint(
            model_name="series",
            constraint=models.UniqueConstraint(
                fields=("library", "series_rel_path"),
                name="manga_series_unique_library_path",
            ),
        ),
        migrations.AddIndex(
            model_name="series",
            index=models.Index(fields=["library", "category"], name="manga_series_lib_category"),
        ),
    ]
