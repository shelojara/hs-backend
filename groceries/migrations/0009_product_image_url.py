from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("groceries", "0008_product_standard_name"),
    ]

    operations = [
        migrations.AddField(
            model_name="product",
            name="image_url",
            field=models.URLField(blank=True, default="", max_length=2048),
        ),
    ]
