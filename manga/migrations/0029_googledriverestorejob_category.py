# Generated manually: restore target path uses <category>/<series_name>.

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("manga", "0028_googledriverestorejob"),
    ]

    operations = [
        migrations.AddField(
            model_name="googledriverestorejob",
            name="category",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Library subdirectory under manga root; files go to <root>/<category>/<series_name>/.",
                max_length=1024,
            ),
        ),
    ]
