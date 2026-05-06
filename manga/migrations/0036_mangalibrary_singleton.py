import os

from django.db import migrations, models


def merge_manga_library_singleton(apps, schema_editor):
    MangaLibrary = apps.get_model("manga", "MangaLibrary")
    rows = list(MangaLibrary.objects.order_by("pk"))
    if not rows:
        MangaLibrary.objects.create(
            pk=1,
            name="Default",
            fs_path=os.path.abspath(os.path.expanduser("/manga")),
        )
        return
    first = rows[0]
    name = first.name
    fs_path = first.fs_path
    MangaLibrary.objects.all().delete()
    MangaLibrary.objects.create(pk=1, name=name, fs_path=fs_path)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("manga", "0035_mangalibrary"),
    ]

    operations = [
        migrations.RunPython(merge_manga_library_singleton, noop_reverse),
        migrations.AlterModelOptions(
            name="mangalibrary",
            options={
                "ordering": ("pk",),
                "verbose_name": "manga library",
                "verbose_name_plural": "manga library",
            },
        ),
        migrations.AddConstraint(
            model_name="mangalibrary",
            constraint=models.CheckConstraint(
                condition=models.Q(pk=1),
                name="manga_mangalibrary_singleton_pk",
            ),
        ),
    ]
