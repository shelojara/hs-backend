# Generated manually: Gemini search query kind (admin-only).

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("groceries", "0031_search_deleted_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="search",
            name="kind",
            field=models.CharField(
                blank=True,
                choices=[
                    ("product", "Product"),
                    ("brand", "Brand"),
                    ("recipe", "Recipe"),
                    ("question", "Question"),
                ],
                db_index=True,
                default="",
                max_length=16,
            ),
        ),
    ]
