# Reassign placeholder owner to production user "shelo" if 0022 used _migration_owner.

from django.conf import settings
from django.db import migrations


def _reassign_to_shelo(apps, schema_editor):
    User = apps.get_model("auth", "User")
    Page = apps.get_model("pagechecker", "Page")
    Question = apps.get_model("pagechecker", "Question")
    old = User.objects.filter(username="_migration_owner").first()
    shelo = User.objects.filter(username="shelo").first()
    if old is None or shelo is None or old.pk == shelo.pk:
        return
    Page.objects.filter(owner_id=old.pk).update(owner_id=shelo.pk)
    Question.objects.filter(owner_id=old.pk).update(owner_id=shelo.pk)
    old.delete()


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("pagechecker", "0022_page_question_owner"),
    ]

    operations = [
        migrations.RunPython(_reassign_to_shelo, migrations.RunPython.noop),
    ]
