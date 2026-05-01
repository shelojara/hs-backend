from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("savings", "0003_familymembership_one_family_per_user"),
    ]

    operations = [
        migrations.AddField(
            model_name="distribution",
            name="notes",
            field=models.TextField(blank=True, default=""),
        ),
    ]
