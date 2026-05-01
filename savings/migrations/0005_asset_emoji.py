from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("savings", "0004_distribution_notes"),
    ]

    operations = [
        migrations.AddField(
            model_name="asset",
            name="emoji",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Display emoji for this goal (often suggested via Gemini).",
                max_length=64,
            ),
        ),
    ]
