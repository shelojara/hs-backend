"""Many-to-many between Page and Question."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("pagechecker", "0011_question"),
    ]

    operations = [
        migrations.AddField(
            model_name="page",
            name="questions",
            field=models.ManyToManyField(
                blank=True,
                related_name="pages",
                to="pagechecker.question",
            ),
        ),
    ]
