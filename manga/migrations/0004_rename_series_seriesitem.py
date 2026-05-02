# Rename cached library models to Series and SeriesItem.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("manga", "0003_manga_library_cache_schedule"),
    ]

    operations = [
        migrations.RenameModel(
            old_name="MangaLibrarySeries",
            new_name="Series",
        ),
        migrations.RenameModel(
            old_name="MangaLibraryChapter",
            new_name="SeriesItem",
        ),
    ]
