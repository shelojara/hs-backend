from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("groceries", "0049_product_quantity"),
    ]

    operations = [
        migrations.AddField(
            model_name="search",
            name="failure_message",
            field=models.TextField(blank=True, default=""),
        ),
    ]
