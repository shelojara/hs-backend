from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("groceries", "0032_search_kind"),
    ]

    operations = [
        migrations.AddField(
            model_name="search",
            name="parent",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="child_searches",
                to="groceries.search",
            ),
        ),
    ]
