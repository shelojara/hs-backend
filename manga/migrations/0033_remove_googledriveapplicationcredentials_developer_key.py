# Remove browser API key field (Google Picker integration removed).

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("manga", "0032_googledriveapplicationcredentials_developer_key"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="googledriveapplicationcredentials",
            name="developer_key",
        ),
    ]
