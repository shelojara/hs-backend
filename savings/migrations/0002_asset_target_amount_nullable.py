# Generated manually for nullable savings goal target.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("savings", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="asset",
            name="target_amount",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                max_digits=14,
                null=True,
            ),
        ),
    ]
