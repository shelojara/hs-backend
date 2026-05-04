from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("manga", "0019_seriesinfo_refetch_for_mangabaka_type"),
    ]

    operations = [
        migrations.RenameField(
            model_name="seriesinfo",
            old_name="mangabaka_type",
            new_name="series_type",
        ),
    ]
