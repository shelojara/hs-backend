from django.db import migrations, models


SEARCH_DEFAULT_EMOJI = "\N{LEFT-POINTING MAGNIFYING GLASS}"


class Migration(migrations.Migration):
    dependencies = [
        ("groceries", "0039_recipe_notes"),
    ]

    operations = [
        migrations.AddField(
            model_name="search",
            name="emoji",
            field=models.CharField(
                max_length=64,
                blank=True,
                default=SEARCH_DEFAULT_EMOJI,
            ),
            preserve_default=True,
        ),
    ]
