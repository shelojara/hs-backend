from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("groceries", "0009_product_image_url"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="product",
            name="image_url",
        ),
        migrations.AddField(
            model_name="product",
            name="emoji",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
    ]
