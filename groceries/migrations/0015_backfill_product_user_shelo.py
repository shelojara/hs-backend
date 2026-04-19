# Data migration: assign all products to user ``shelo`` when that user exists.

from django.conf import settings
from django.db import migrations


def forwards(apps, schema_editor):
    Product = apps.get_model("groceries", "Product")
    app_label, model_name = settings.AUTH_USER_MODEL.split(".")
    User = apps.get_model(app_label, model_name)
    try:
        shelo = User.objects.get(username="shelo")
    except User.DoesNotExist:
        return
    Product.objects.all().update(user_id=shelo.pk)


def backwards(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("groceries", "0014_product_user_fk"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
