# Generated manually for running-low manual snooze.

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("groceries", "0047_recipe_emoji_default_magnifying_glass"),
    ]

    operations = [
        migrations.AddField(
            model_name="product",
            name="running_low_snoozed_until",
            field=models.DateTimeField(
                blank=True,
                help_text="When set, scheduled running-low sync skips re-flagging until this instant.",
                null=True,
            ),
        ),
    ]
