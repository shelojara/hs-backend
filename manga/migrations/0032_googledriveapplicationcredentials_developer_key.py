# Generated manually: browser API key for Google Picker (admin browse only).

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("manga", "0031_remove_googledriveapplicationcredentials_picker_fields"),
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
    ]
