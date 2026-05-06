# MangaLibrary (global) + Series.library FK; backfill from library_root.

import os
from collections import defaultdict

import django.db.models.deletion
from django.db import migrations, models


def forwards_backfill_libraries(apps, schema_editor):
    Series = apps.get_model("manga", "Series")
    MangaLibrary = apps.get_model("manga", "MangaLibrary")

    by_norm: dict[str, list[int]] = defaultdict(list)
    for pk, lr in Series.objects.values_list("pk", "library_root"):
        key = os.path.abspath(os.path.expanduser(lr or ""))
        by_norm[key].append(pk)

    used_names: set[str] = set()
    for norm_root, pks in by_norm.items():
        if not norm_root:
            continue
        base = os.path.basename(norm_root.rstrip(os.sep)) or "library"
        name = base
        n = 0
        while name in used_names:
            n += 1
            name = f"{base} ({n})"
        used_names.add(name)
        lib = MangaLibrary.objects.create(
            name=name,
            filesystem_path=norm_root,
        )
        Series.objects.filter(pk__in=pks).update(library_id=lib.pk)


def backwards_clear_library_fk(apps, schema_editor):
    Series = apps.get_model("manga", "Series")
    Series.objects.all().update(library_id=None)


class Migration(migrations.Migration):
    dependencies = [
        ("manga", "0034_manga_library_cache_schedule_every_30m"),
    ]

    operations = [
        migrations.CreateModel(
            name="MangaLibrary",
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
                    "name",
                    models.CharField(max_length=256),
                ),
                (
                    "filesystem_path",
                    models.CharField(
                        help_text="Absolute path on server where .cbz library lives.",
                        max_length=4096,
                    ),
                ),
            ],
            options={
                "verbose_name": "manga library",
                "verbose_name_plural": "manga libraries",
                "ordering": ("name", "pk"),
            },
        ),
        migrations.AddConstraint(
            model_name="mangalibrary",
            constraint=models.UniqueConstraint(
                fields=("filesystem_path",),
                name="manga_mangalibrary_filesystem_path_uniq",
            ),
        ),
        migrations.AddField(
            model_name="series",
            name="library",
            field=models.ForeignKey(
                null=True,
                blank=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="series_set",
                to="manga.mangalibrary",
            ),
        ),
        migrations.RunPython(forwards_backfill_libraries, backwards_clear_library_fk),
        migrations.RemoveConstraint(
            model_name="series",
            name="manga_mangalibraryseries_unique_root_path",
        ),
        migrations.RemoveIndex(
            model_name="series",
            name="manga_series_root_category",
        ),
        migrations.AlterField(
            model_name="series",
            name="library",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="series_set",
                to="manga.mangalibrary",
            ),
        ),
        migrations.AlterField(
            model_name="series",
            name="library_root",
            field=models.CharField(
                help_text="Denormalized copy of library filesystem path when row was written (legacy / jobs).",
                max_length=4096,
            ),
        ),
        migrations.AddConstraint(
            model_name="series",
            constraint=models.UniqueConstraint(
                fields=("library", "series_rel_path"),
                name="manga_series_unique_library_seriespath",
            ),
        ),
        migrations.AddIndex(
            model_name="series",
            index=models.Index(
                fields=["library", "category"],
                name="manga_series_library_category",
            ),
        ),
    ]
