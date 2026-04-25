from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("groceries", "0042_remove_search_kind_and_parent"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="search",
            name="job_type",
            field=models.CharField(
                db_index=True,
                default="product",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="search",
            name="recipe_notes",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="search",
            name="recipe",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.SET_NULL,
                related_name="source_searches",
                to="groceries.recipe",
            ),
        ),
    ]
