# Generated manually for one-family-per-user rule.

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("savings", "0002_asset_target_amount_nullable"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="familymembership",
            constraint=models.UniqueConstraint(
                fields=("user",),
                name="savings_family_membership_one_per_user",
            ),
        ),
    ]
