from django.db import migrations, models
from django.utils import timezone


def backfill_completed_at(apps, schema_editor):
    Asset = apps.get_model("savings", "Asset")
    Asset.objects.filter(state="COMPLETED", completed_at__isnull=True).update(
        completed_at=timezone.now()
    )


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("savings", "0006_asset_state"),
    ]

    operations = [
        migrations.AddField(
            model_name="asset",
            name="completed_at",
            field=models.DateTimeField(
                blank=True,
                help_text="When the goal was marked completed (null while active).",
                null=True,
            ),
        ),
        migrations.RunPython(backfill_completed_at, noop_reverse),
    ]
