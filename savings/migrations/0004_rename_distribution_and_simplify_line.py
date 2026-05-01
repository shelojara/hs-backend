# Generated manually for Distribution rename + DistributionLine simplification

import django.db.models.deletion
from django.db import migrations, models


def delete_lines_without_asset(apps, schema_editor):
    DistributionLine = apps.get_model("savings", "DistributionLine")
    DistributionLine.objects.filter(asset_id__isnull=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("savings", "0003_remove_family_name"),
    ]

    operations = [
        migrations.RenameModel(
            old_name="DistributionSession",
            new_name="Distribution",
        ),
        migrations.RenameField(
            model_name="distributionline",
            old_name="session",
            new_name="distribution",
        ),
        migrations.RemoveConstraint(
            model_name="distribution",
            name="savings_session_scope_family_consistent",
        ),
        migrations.AddConstraint(
            model_name="distribution",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(
                        ("family__isnull", True),
                        ("scope", "PERSONAL"),
                    )
                    | models.Q(
                        ("family__isnull", False),
                        ("scope", "FAMILY"),
                    ),
                ),
                name="savings_distribution_scope_family_consistent",
            ),
        ),
        migrations.RunPython(delete_lines_without_asset, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="distributionline",
            name="asset",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="distribution_lines",
                to="savings.savingsasset",
            ),
        ),
        migrations.RemoveField(
            model_name="distributionline",
            name="asset_name_snapshot",
        ),
        migrations.RemoveField(
            model_name="distributionline",
            name="weight_snapshot",
        ),
        migrations.RemoveField(
            model_name="distributionline",
            name="selected",
        ),
        migrations.RemoveField(
            model_name="distributionline",
            name="share_percent",
        ),
    ]
