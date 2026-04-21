from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("groceries", "0025_basketproduct_purchase"),
    ]

    operations = [
        migrations.AddField(
            model_name="product",
            name="deleted_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
