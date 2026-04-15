"""Remove Snapshot.features JSON field."""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("pagechecker", "0012_page_questions"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="snapshot",
            name="features",
        ),
    ]
