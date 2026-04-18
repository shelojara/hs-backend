from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("groceries", "0007_basket_owner"),
    ]

    operations = [
        migrations.AddField(
            model_name="product",
            name="standard_name",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
    ]
