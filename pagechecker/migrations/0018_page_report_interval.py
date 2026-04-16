# Nullable report_interval + last_scheduled_report_at; backfill daily flag to DAILY.

from django.db import migrations, models


def backfill_daily_report_interval(apps, schema_editor):
    Page = apps.get_model("pagechecker", "Page")
    Page.objects.filter(should_report_daily=True).update(report_interval="DAILY")


def reverse_clear_report_interval(apps, schema_editor):
    Page = apps.get_model("pagechecker", "Page")
    Page.objects.all().update(report_interval=None, last_scheduled_report_at=None)


class Migration(migrations.Migration):
    dependencies = [
        ("pagechecker", "0017_daily_page_check_schedule"),
    ]

    operations = [
        migrations.AddField(
            model_name="page",
            name="report_interval",
            field=models.CharField(
                blank=True,
                choices=[
                    ("DAILY", "Daily"),
                    ("WEEKLY", "Weekly"),
                    ("MONTHLY", "Monthly"),
                ],
                max_length=16,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="page",
            name="last_scheduled_report_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(backfill_daily_report_interval, reverse_clear_report_interval),
    ]
