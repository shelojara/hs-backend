# Merge migration: parallel 0011 branches (category field vs seriesitem file_created_at).

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("manga", "0011_series_category_field"),
        ("manga", "0011_seriesitem_file_created_at"),
    ]

    operations = []
