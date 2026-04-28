from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("groceries", "0051_alter_search_failure_message_nullable"),
    ]

    operations = [
        migrations.AlterField(
            model_name="search",
            name="result_candidates",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
