"""Drop Snapshot.content; md_content is canonical for storage and Gemini."""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("pagechecker", "0009_snapshot_md_content"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="snapshot",
            name="content",
        ),
    ]
