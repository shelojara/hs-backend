from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("groceries", "0029_search_create_at"),
    ]

    operations = [
        migrations.RenameField(
            model_name="search",
            old_name="create_at",
            new_name="created_at",
        ),
    ]
