from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("groceries", "0050_search_failure_message"),
    ]

    operations = [
        migrations.AlterField(
            model_name="search",
            name="failure_message",
            field=models.TextField(blank=True, null=True),
        ),
    ]
