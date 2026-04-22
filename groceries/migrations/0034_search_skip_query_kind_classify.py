from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("groceries", "0033_search_parent"),
    ]

    operations = [
        migrations.AddField(
            model_name="search",
            name="skip_query_kind_classify",
            field=models.BooleanField(
                default=False,
                help_text="When true, product search job treats query as product search without Gemini classifier.",
            ),
        ),
    ]
