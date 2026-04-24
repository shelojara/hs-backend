from django.db import migrations


def delete_child_searches(apps, schema_editor):
    Search = apps.get_model("groceries", "Search")
    conn = schema_editor.connection
    table = conn.ops.quote_name(Search._meta.db_table)
    # Hard-delete all child rows (including soft-deleted) so parent FK can be dropped.
    with conn.cursor() as cursor:
        cursor.execute(f"DELETE FROM {table} WHERE parent_id IS NOT NULL")


class Migration(migrations.Migration):
    dependencies = [
        ("groceries", "0040_search_emoji"),
    ]

    operations = [
        migrations.RunPython(delete_child_searches, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="search",
            name="parent",
        ),
        migrations.RemoveField(
            model_name="search",
            name="kind",
        ),
        migrations.DeleteModel(
            name="RecipeStep",
        ),
        migrations.DeleteModel(
            name="RecipeIngredient",
        ),
        migrations.DeleteModel(
            name="Recipe",
        ),
    ]
