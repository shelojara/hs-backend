# Search creation timestamp for ordering and API.

import django.utils.timezone
from django.db import migrations, models
from django.db.models import F


def backfill_search_create_at(apps, schema_editor):
    Search = apps.get_model("groceries", "Search")
    now = django.utils.timezone.now()
    Search.objects.exclude(completed_at__isnull=True).update(create_at=F("completed_at"))
    Search.objects.filter(completed_at__isnull=True).update(create_at=now)


class Migration(migrations.Migration):

    dependencies = [
        ("groceries", "0028_search"),
    ]

    operations = [
        migrations.AddField(
            model_name="search",
            name="create_at",
            field=models.DateTimeField(null=True),
        ),
        migrations.RunPython(backfill_search_create_at, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="search",
            name="create_at",
            field=models.DateTimeField(auto_now_add=True),
        ),
    ]
