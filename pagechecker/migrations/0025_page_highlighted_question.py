# Generated manually for Page.highlighted_question

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("pagechecker", "0024_api_key"),
    ]

    operations = [
        migrations.AddField(
            model_name="page",
            name="highlighted_question",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="highlighted_on_pages",
                to="pagechecker.question",
            ),
        ),
    ]
