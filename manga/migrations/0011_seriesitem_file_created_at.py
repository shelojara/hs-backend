import os
from datetime import UTC, datetime

from django.db import migrations, models


def backfill_file_created_at(apps, schema_editor):
    SeriesItem = apps.get_model("manga", "SeriesItem")

    def filesystem_created_at(st) -> datetime | None:
        birth = getattr(st, "st_birthtime", None)
        ts = float(birth) if birth is not None else float(st.st_ctime)
        try:
            return datetime.fromtimestamp(ts, tz=UTC)
        except (OSError, OverflowError, ValueError):
            return None

    qs = SeriesItem.objects.select_related("series").iterator(chunk_size=500)
    for row in qs:
        root = row.series.library_root
        rel = row.rel_path
        abs_path = os.path.abspath(os.path.join(root, rel.replace("/", os.sep)))
        root_abs = os.path.abspath(root)
        try:
            common = os.path.commonpath([root_abs, abs_path])
        except ValueError:
            continue
        if common != root_abs:
            continue
        if not os.path.isfile(abs_path):
            continue
        try:
            st = os.stat(abs_path)
        except OSError:
            continue
        ts = filesystem_created_at(st)
        if ts is None:
            continue
        SeriesItem.objects.filter(pk=row.pk).update(file_created_at=ts)


class Migration(migrations.Migration):
    dependencies = [
        ("manga", "0010_series_item_count"),
    ]

    operations = [
        migrations.AddField(
            model_name="seriesitem",
            name="file_created_at",
            field=models.DateTimeField(
                blank=True,
                help_text=(
                    "Best-effort filesystem birth/creation time for the CBZ when synced "
                    "(platform-dependent; falls back to metadata change time)."
                ),
                null=True,
            ),
        ),
        migrations.RunPython(backfill_file_created_at, migrations.RunPython.noop),
    ]
