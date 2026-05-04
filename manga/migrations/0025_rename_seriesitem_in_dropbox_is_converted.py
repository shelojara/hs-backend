from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("manga", "0024_googledriveapplicationcredentials"),
    ]

    operations = [
        migrations.RenameField(
            model_name="seriesitem",
            old_name="in_dropbox",
            new_name="is_converted",
        ),
    ]
