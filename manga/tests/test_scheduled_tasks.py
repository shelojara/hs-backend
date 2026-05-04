"""Tests for manga django-q schedules."""

import pytest
from django_q.models import Schedule


@pytest.mark.django_db
def test_manga_library_cache_schedule_cron_every_five_minutes():
    row = Schedule.objects.get(name="manga_library_cache_refresh")
    assert row.schedule_type == Schedule.CRON
    assert row.cron == "*/5 * * * *"


@pytest.mark.django_db
def test_mangabaka_series_info_schedule_cron_every_five_minutes():
    row = Schedule.objects.get(name="manga_mangabaka_series_info_sync")
    assert row.schedule_type == Schedule.CRON
    assert row.cron == "*/5 * * * *"
