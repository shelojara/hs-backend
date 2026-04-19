from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("groceries", "0012_product_is_custom"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="product",
            name="original_name",
        ),
    ]
