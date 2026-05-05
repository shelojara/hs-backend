# Generated manually: remove picker fields; manga library folder stays under My Drive root.

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("manga", "0030_googledriveapplicationcredentials_picker_fields"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="googledriveapplicationcredentials",
            name="developer_key",
        ),
        migrations.RemoveField(
            model_name="googledriveapplicationcredentials",
            name="parent_folder_id",
        ),
    ]
