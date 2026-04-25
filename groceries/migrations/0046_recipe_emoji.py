from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("groceries", "0045_recipe_generation_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="recipe",
            name="emoji",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
    ]
