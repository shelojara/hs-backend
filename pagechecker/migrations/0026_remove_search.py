# Generated manually — Search model moved to groceries app.

from django.db import migrations


def _copy_pagechecker_searches_to_groceries(apps, schema_editor):
    OldSearch = apps.get_model("pagechecker", "Search")
    NewSearch = apps.get_model("groceries", "Search")
    for old in OldSearch.objects.all().order_by("id"):
        NewSearch.objects.create(
            id=old.id,
            user_id=old.user_id,
            query=old.query,
            status=old.status,
            result_candidates=old.result_candidates,
            completed_at=old.completed_at,
        )


def _noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("pagechecker", "0025_search"),
        ("groceries", "0028_search"),
    ]

    operations = [
        migrations.RunPython(_copy_pagechecker_searches_to_groceries, _noop_reverse),
        migrations.DeleteModel(
            name="Search",
        ),
    ]
