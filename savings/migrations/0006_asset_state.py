from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("savings", "0005_asset_emoji"),
    ]

    operations = [
        migrations.AddField(
            model_name="asset",
            name="state",
            field=models.CharField(
                choices=[("ACTIVE", "Active"), ("COMPLETED", "Completed")],
                db_index=True,
                default="ACTIVE",
                help_text="Completed goals are excluded from new distributions and rush transfers.",
                max_length=16,
            ),
        ),
    ]
