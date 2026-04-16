# Generated manually for user ownership of Page and Question.

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


def _assign_page_owners(apps, schema_editor):
    Page = apps.get_model("pagechecker", "Page")
    user = _backfill_owner_user(apps)
    if user is None:
        return
    Page.objects.filter(owner_id__isnull=True).update(owner_id=user.pk)


def _assign_question_owners(apps, schema_editor):
    Question = apps.get_model("pagechecker", "Question")
    user = _backfill_owner_user(apps)
    if user is None:
        return
    Question.objects.filter(owner_id__isnull=True).update(owner_id=user.pk)


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("pagechecker", "0021_remove_page_should_report_daily"),
    ]

    operations = [
        migrations.RunPython(_ensure_shelo_user, migrations.RunPython.noop),
        migrations.AddField(
            model_name="page",
            name="owner",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="pages",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.RunPython(_assign_page_owners, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="page",
            name="owner",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="pages",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name="page",
            name="url",
            field=models.URLField(),
        ),
        migrations.AddConstraint(
            model_name="page",
            constraint=models.UniqueConstraint(
                fields=("owner", "url"),
                name="pagechecker_page_owner_url_uniq",
            ),
        ),
        migrations.AddField(
            model_name="question",
            name="owner",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="questions",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.RunPython(_assign_question_owners, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="question",
            name="owner",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="questions",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
