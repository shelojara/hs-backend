from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("manga", "0029_googledriverestorejob_category"),
    ]

    operations = [
        migrations.AddField(
            model_name="googledriveapplicationcredentials",
            name="browser_api_key",
            field=models.CharField(
                blank=True,
                default="",
                help_text=(
                    "Browser API key for Google Picker (optional). Restrict this key by HTTP "
                    "referrer in Google Cloud Console."
                ),
                max_length=256,
            ),
        ),
    ]
