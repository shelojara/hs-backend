# django-q2: refresh manga library DB cache every 30 minutes (TIME_ZONE).

from django.db import migrations


SCHEDULE_NAME = "manga_library_cache_refresh"


def forwards(apps, schema_editor):
    Schedule = apps.get_model("django_q", "Schedule")
    Schedule.objects.filter(name=SCHEDULE_NAME).update(cron="*/30 * * * *")


def backwards(apps, schema_editor):
    Schedule = apps.get_model("django_q", "Schedule")
    Schedule.objects.filter(name=SCHEDULE_NAME).update(cron="*/5 * * * *")


class Migration(migrations.Migration):
    dependencies = [
        ("django_q", "0018_task_success_index"),
        ("manga", "0033_remove_googledriveapplicationcredentials_developer_key"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
