from decimal import Decimal

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("groceries", "0026_product_deleted_at"),
    ]

    operations = [
        migrations.AlterField(
            model_name="product",
            name="price",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                default=Decimal("0"),
                max_digits=12,
                null=True,
            ),
        ),
    ]
