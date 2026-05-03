# Remove soft-delete column from CbzConvertJob (no API delete path).

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("manga", "0006_cbzconvertjob"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="cbzconvertjob",
            name="deleted_at",
        ),
    ]
