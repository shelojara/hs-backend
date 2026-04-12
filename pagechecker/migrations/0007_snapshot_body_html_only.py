"""Store only body inner HTML in Snapshot.html_content (strip head/doctype)."""

from django.db import migrations

from pagechecker.html_utils import extract_body_html


def shrink_snapshot_html(apps, schema_editor):
    Snapshot = apps.get_model("pagechecker", "Snapshot")
    for snapshot in Snapshot.objects.exclude(html_content="").iterator():
        new_html = extract_body_html(snapshot.html_content)
        if new_html != snapshot.html_content:
            snapshot.html_content = new_html
            snapshot.save(update_fields=["html_content"])


class Migration(migrations.Migration):

    dependencies = [
        ("pagechecker", "0006_backfill_page_title_icon"),
    ]

    operations = [
        migrations.RunPython(shrink_snapshot_html, migrations.RunPython.noop),
    ]
