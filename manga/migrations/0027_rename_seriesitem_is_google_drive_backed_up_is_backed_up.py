from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("manga", "0026_seriesitem_is_google_drive_backed_up"),
    ]

    operations = [
        migrations.RenameField(
            model_name="seriesitem",
            old_name="is_google_drive_backed_up",
            new_name="is_backed_up",
        ),
    ]
