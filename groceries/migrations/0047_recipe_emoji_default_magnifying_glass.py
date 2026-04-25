from django.db import migrations, models

# Same as groceries.models.SEARCH_DEFAULT_EMOJI (avoid importing app models in migrations).
RECIPE_DEFAULT_EMOJI = "\N{LEFT-POINTING MAGNIFYING GLASS}"


def backfill_recipe_emoji_empty(apps, schema_editor):
    Recipe = apps.get_model("groceries", "Recipe")
    Recipe.objects.filter(emoji="").update(emoji=RECIPE_DEFAULT_EMOJI)


class Migration(migrations.Migration):
    dependencies = [
        ("groceries", "0046_recipe_emoji"),
    ]

    operations = [
        migrations.RunPython(backfill_recipe_emoji_empty, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="recipe",
            name="emoji",
            field=models.CharField(
                blank=True,
                default=RECIPE_DEFAULT_EMOJI,
                max_length=64,
            ),
        ),
    ]
