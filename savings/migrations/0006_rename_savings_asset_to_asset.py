# Rename SavingsAsset model to Asset

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("savings", "0005_align_distribution_metadata"),
    ]

    operations = [
        migrations.RenameModel(
            old_name="SavingsAsset",
            new_name="Asset",
        ),
    ]
