# Basket ownership (per-user open basket and history).

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def _ensure_shelo_user(apps, schema_editor):
    User = apps.get_model("auth", "User")
    if User.objects.filter(username="shelo").exists():
        return
    User.objects.create_user(
        username="shelo",
        email="",
        password="migration-placeholder-not-for-login",
    )


def _backfill_owner_user(apps):
    User = apps.get_model("auth", "User")
    u = User.objects.filter(username="shelo").first()
    if u is not None:
        return u
    return User.objects.order_by("id").first()


def _assign_basket_owners(apps, schema_editor):
    Basket = apps.get_model("groceries", "Basket")
    user = _backfill_owner_user(apps)
    if user is None:
        return
    Basket.objects.filter(owner_id__isnull=True).update(owner_id=user.pk)


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("groceries", "0006_rename_purchase_to_basket"),
    ]

    operations = [
        migrations.RunPython(_ensure_shelo_user, migrations.RunPython.noop),
        migrations.AddField(
            model_name="basket",
            name="owner",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="baskets",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.RunPython(_assign_basket_owners, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="basket",
            name="owner",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="baskets",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
