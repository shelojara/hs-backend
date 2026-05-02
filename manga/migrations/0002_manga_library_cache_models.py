# Generated manually

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("manga", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="MangaLibrarySeries",
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
                    "library_root",
                    models.CharField(
                        help_text="Normalized absolute path to manga library root when this row was written.",
                        max_length=4096,
                    ),
                ),
                (
                    "series_rel_path",
                    models.CharField(
                        help_text="Path under library root (POSIX-style); empty string means CBZs sit at library root.",
                        max_length=1024,
                    ),
                ),
                (
                    "name",
                    models.CharField(
                        help_text="Directory basename for this series (or library folder name when series_rel_path is empty).",
                        max_length=1024,
                    ),
                ),
                ("scanned_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "manga library series (cached)",
                "verbose_name_plural": "manga library series (cached)",
                "ordering": ("library_root", "series_rel_path"),
            },
        ),
        migrations.CreateModel(
            name="MangaLibraryChapter",
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
                    "rel_path",
                    models.CharField(
                        help_text="File path under library root (POSIX-style), e.g. MySeries/ch01.cbz",
                        max_length=1024,
                    ),
                ),
                ("filename", models.CharField(max_length=512)),
                ("size_bytes", models.BigIntegerField(blank=True, null=True)),
                ("in_dropbox", models.BooleanField(default=False)),
                (
                    "series",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="chapters",
                        to="manga.mangalibraryseries",
                    ),
                ),
            ],
            options={
                "verbose_name": "manga library chapter (cached)",
                "verbose_name_plural": "manga library chapters (cached)",
                "ordering": ("series", "rel_path"),
            },
        ),
        migrations.AddConstraint(
            model_name="mangalibraryseries",
            constraint=models.UniqueConstraint(
                fields=("library_root", "series_rel_path"),
                name="manga_mangalibraryseries_unique_root_path",
            ),
        ),
        migrations.AddConstraint(
            model_name="mangalibrarychapter",
            constraint=models.UniqueConstraint(
                fields=("series", "rel_path"),
                name="manga_mangalibrarychapter_unique_series_relpath",
            ),
        ),
    ]
