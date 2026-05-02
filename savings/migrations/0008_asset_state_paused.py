from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("savings", "0007_asset_completed_at"),
    ]

    operations = [
        migrations.AlterField(
            model_name="asset",
            name="state",
            field=models.CharField(
                choices=[
                    ("ACTIVE", "Active"),
                    ("PAUSED", "Paused"),
                    ("COMPLETED", "Completed"),
                ],
                db_index=True,
                default="ACTIVE",
                help_text="Completed: excluded from distributions and rush. Paused: excluded from "
                "distributions only; may still appear in rush.",
                max_length=16,
            ),
        ),
    ]
