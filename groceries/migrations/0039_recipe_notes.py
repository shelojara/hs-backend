from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("groceries", "0038_remove_recipe_body_source_url_and_ingredient_product"),
    ]

    operations = [
        migrations.AddField(
            model_name="recipe",
            name="notes",
            field=models.TextField(blank=True, default=""),
        ),
    ]
