# Merchant preference order; backfill uses each row's created_at (2026-04-19).

from django.db import migrations, models


def _backfill_preference_order(apps, schema_editor):
    Merchant = apps.get_model("groceries", "Merchant")
    db_alias = schema_editor.connection.alias
    user_ids = (
        Merchant.objects.using(db_alias)
        .values_list("user_id", flat=True)
        .distinct()
    )
    for uid in user_ids:
        rows = list(
            Merchant.objects.using(db_alias)
            .filter(user_id=uid)
            .order_by("created_at", "pk")
        )
        for i, m in enumerate(rows):
            Merchant.objects.using(db_alias).filter(pk=m.pk).update(
                preference_order=i,
            )


class Migration(migrations.Migration):

    dependencies = [
        ("groceries", "0021_merchant"),
    ]

    operations = [
        migrations.AddField(
            model_name="merchant",
            name="preference_order",
            field=models.PositiveIntegerField(
                default=0,
                help_text="Lower = higher priority (first in preferred list).",
                null=True,
            ),
        ),
        migrations.RunPython(_backfill_preference_order, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="merchant",
            name="preference_order",
            field=models.PositiveIntegerField(
                default=0,
                help_text="Lower = higher priority (first in preferred list).",
            ),
        ),
        migrations.AlterModelOptions(
            name="merchant",
            options={"ordering": ("preference_order", "pk")},
        ),
        migrations.AddConstraint(
            model_name="merchant",
            constraint=models.UniqueConstraint(
                fields=("user", "preference_order"),
                name="groceries_merchant_user_preference_order_uniq",
            ),
        ),
    ]
