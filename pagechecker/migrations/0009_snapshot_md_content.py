"""Add Snapshot.md_content; backfill from html_content via markdownify."""

from django.db import migrations, models

from pagechecker.html_utils import html_to_markdown


def backfill_md_content(apps, schema_editor):
    Snapshot = apps.get_model("pagechecker", "Snapshot")
    for snapshot in Snapshot.objects.exclude(html_content="").iterator():
        md = html_to_markdown(snapshot.html_content)
        if md != snapshot.md_content:
            snapshot.md_content = md
            snapshot.save(update_fields=["md_content"])


class Migration(migrations.Migration):
    dependencies = [
        ("pagechecker", "0008_snapshot_features"),
    ]

    operations = [
        migrations.AddField(
            model_name="snapshot",
            name="md_content",
            field=models.TextField(default=""),
        ),
        migrations.RunPython(backfill_md_content, migrations.RunPython.noop),
    ]
