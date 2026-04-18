# Seed django-q2 Schedule rows for page check dispatchers (replaces legacy migration data).

from django.db import migrations


def forwards(apps, schema_editor):
    # django-q Schedule lives in django_q app, not migrated via our models.
    from django_q.models import Schedule

    schedules = [
        (
            "daily_page_check_dispatcher",
            "pagechecker.scheduled_tasks.run_daily_page_check_dispatch",
            "0 9 * * *",
        ),
        (
            "weekly_page_check_dispatcher",
            "pagechecker.scheduled_tasks.run_weekly_page_check_dispatch",
            "30 9 * * 5",
        ),
        (
            "monthly_page_check_dispatcher",
            "pagechecker.scheduled_tasks.run_monthly_page_check_dispatch",
            "0 10 5 * *",
        ),
    ]
    for name, func, cron in schedules:
        Schedule.objects.update_or_create(
            name=name,
            defaults={
                "func": func,
                "schedule_type": Schedule.CRON,
                "cron": cron,
                "repeats": -1,
            },
        )


def backwards(apps, schema_editor):
    from django_q.models import Schedule

    Schedule.objects.filter(
        name__in=(
            "daily_page_check_dispatcher",
            "weekly_page_check_dispatcher",
            "monthly_page_check_dispatcher",
        )
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("pagechecker", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
