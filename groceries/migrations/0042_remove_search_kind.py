from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("groceries", "0041_remove_whiteboard"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="search",
            name="kind",
        ),
    ]
