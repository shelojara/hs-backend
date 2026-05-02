# Generated manually for manga app

from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="MangaHiddenDirectory",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "rel_path",
                    models.CharField(
                        help_text="Path under manga root using forward slashes, e.g. archive/old or Series Name",
                        max_length=1024,
                        unique=True,
                    ),
                ),
            ],
            options={
                "verbose_name": "hidden manga directory",
                "verbose_name_plural": "hidden manga directories",
                "ordering": ("rel_path",),
            },
        ),
    ]
