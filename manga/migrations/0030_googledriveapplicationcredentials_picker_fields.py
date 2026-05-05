# Generated manually: Google Picker (admin) parent folder id + API browser key.

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("manga", "0029_googledriverestorejob_category"),
    ]

    operations = [
        migrations.AddField(
            model_name="googledriveapplicationcredentials",
            name="developer_key",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Google Cloud browser API key (Picker in admin). Restrict HTTP referrers to this site.",
                max_length=256,
            ),
        ),
        migrations.AddField(
            model_name="googledriveapplicationcredentials",
            name="parent_folder_id",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Drive folder id where the library root folder is created (default: My Drive). Use Pick folder or paste id.",
                max_length=128,
            ),
        ),
    ]
