# Generated manually for django-q2 daily dispatcher schedule.

from django.db import migrations
from django.utils import timezone

SCHEDULE_NAME = "daily_page_check_dispatcher"


def create_daily_schedule(apps, schema_editor):
    Schedule = apps.get_model("django_q", "Schedule")
    if Schedule.objects.filter(name=SCHEDULE_NAME).exists():
        return
    Schedule.objects.create(
        name=SCHEDULE_NAME,
        func="pagechecker.scheduled_tasks.run_daily_page_check_dispatch",
        schedule_type="D",
        repeats=-1,
        next_run=timezone.now(),
    )


def remove_daily_schedule(apps, schema_editor):
    Schedule = apps.get_model("django_q", "Schedule")
    Schedule.objects.filter(name=SCHEDULE_NAME).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("django_q", "0018_task_success_index"),
        ("pagechecker", "0016_page_should_report_daily"),
    ]

    operations = [
        migrations.RunPython(create_daily_schedule, remove_daily_schedule),
    ]
