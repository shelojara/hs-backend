from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("groceries", "0040_search_emoji"),
    ]

    operations = [
        migrations.DeleteModel(
            name="Whiteboard",
        ),
    ]
