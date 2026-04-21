# Generated manually for soft-delete on Search.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("groceries", "0030_rename_search_create_at_to_created_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="search",
            name="deleted_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
