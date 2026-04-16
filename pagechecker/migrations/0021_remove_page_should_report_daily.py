from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("pagechecker", "0020_monthly_page_check_schedule"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="page",
            name="should_report_daily",
        ),
    ]
