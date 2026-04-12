"""Backfill title and icon for existing pages using their latest snapshot HTML."""

from django.db import migrations

from pagechecker.html_utils import extract_metadata


def backfill_title_icon(apps, schema_editor):
    Page = apps.get_model("pagechecker", "Page")
    Snapshot = apps.get_model("pagechecker", "Snapshot")

    for page in Page.objects.filter(title="", icon=""):
        snapshot = (
            Snapshot.objects.filter(page=page)
            .exclude(html_content="")
            .order_by("-created_at")
            .first()
        )
        if snapshot is None:
            continue

        metadata = extract_metadata(snapshot.html_content, page.url)
        page.title = metadata["title"]
        page.icon = metadata["icon"]
        page.save(update_fields=["title", "icon"])


class Migration(migrations.Migration):

    dependencies = [
        ("pagechecker", "0005_page_icon_page_title"),
    ]

    operations = [
        migrations.RunPython(backfill_title_icon, migrations.RunPython.noop),
    ]
