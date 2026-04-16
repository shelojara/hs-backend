# Align legacy *should_report_daily* pages with DAILY *report_interval* for scheduled checks.

from django.db import migrations


def backfill_daily_interval_from_legacy_flag(apps, schema_editor):
    Page = apps.get_model("pagechecker", "Page")
    Page.objects.filter(should_report_daily=True).update(report_interval="DAILY")


def reverse_noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("pagechecker", "0018_page_report_interval"),
    ]

    operations = [
        migrations.RunPython(backfill_daily_interval_from_legacy_flag, reverse_noop),
    ]
