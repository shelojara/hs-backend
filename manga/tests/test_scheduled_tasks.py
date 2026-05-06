"""Tests for manga django-q schedules."""

from unittest.mock import patch

import pytest
from django_q.models import Schedule

from manga.scheduled_tasks import run_manga_library_cache_refresh


@pytest.mark.django_db
def test_manga_library_cache_schedule_cron_every_thirty_minutes():
    row = Schedule.objects.get(name="manga_library_cache_refresh")
    assert row.schedule_type == Schedule.CRON
    assert row.cron == "*/30 * * * *"


@pytest.mark.django_db
def test_mangabaka_series_info_schedule_cron_every_five_minutes():
    row = Schedule.objects.get(name="manga_mangabaka_series_info_sync")
    assert row.schedule_type == Schedule.CRON
    assert row.cron == "*/5 * * * *"


@pytest.mark.django_db
def test_run_manga_library_cache_refresh_skips_when_locked():
    import manga.services as manga_services

    with patch.object(
        manga_services,
        "sync_manga_library_cache",
        side_effect=manga_services.LibrarySyncAlreadyRunningError(),
    ):
        run_manga_library_cache_refresh()
