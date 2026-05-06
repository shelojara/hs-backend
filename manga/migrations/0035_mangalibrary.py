import os

from django.conf import settings
from django.db import migrations, models


def seed_default_manga_library(apps, schema_editor):
    MangaLibrary = apps.get_model("manga", "MangaLibrary")
    if MangaLibrary.objects.exists():
        return
    raw = getattr(settings, "MANGA_ROOT", "/manga")
    fs_path = os.path.abspath(os.path.expanduser(str(raw)))
    MangaLibrary.objects.create(name="Default", fs_path=fs_path)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("manga", "0034_manga_library_cache_schedule_every_30m"),
    ]

    operations = [
        migrations.CreateModel(
            name="MangaLibrary",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=256)),
                (
                    "fs_path",
                    models.CharField(
                        help_text="Absolute path on server (expanduser applied when syncing).",
                        max_length=4096,
                        unique=True,
                    ),
                ),
            ],
            options={
                "verbose_name": "manga library",
                "verbose_name_plural": "manga libraries",
                "ordering": ("name", "pk"),
            },
        ),
        migrations.RunPython(seed_default_manga_library, noop_reverse),
    ]
