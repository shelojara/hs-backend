"""Add Category model."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("pagechecker", "0013_remove_snapshot_features"),
    ]

    operations = [
        migrations.CreateModel(
            name="Category",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.TextField()),
                ("emoji", models.CharField(max_length=64)),
            ],
        ),
    ]
