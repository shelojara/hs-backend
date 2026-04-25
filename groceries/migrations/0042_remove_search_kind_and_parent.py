from django.db import migrations


def delete_child_searches(apps, schema_editor):
    # Raw SQL: avoids ORM selecting columns that may be absent on partially migrated DBs.
    table = schema_editor.connection.ops.quote_name("groceries_search")
    schema_editor.execute(f"DELETE FROM {table} WHERE parent_id IS NOT NULL")


class Migration(migrations.Migration):
    dependencies = [
        ("groceries", "0041_remove_whiteboard"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="search",
            name="kind",
        ),
        migrations.RunPython(delete_child_searches, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="search",
            name="parent",
        ),
    ]
