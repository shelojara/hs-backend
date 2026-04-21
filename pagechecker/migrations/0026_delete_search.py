# Search model moved to groceries app.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("pagechecker", "0025_search"),
    ]

    operations = [
        migrations.DeleteModel(name="Search"),
    ]
