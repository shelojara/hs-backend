"""django-q Schedule row for groceries daily running-low sync."""

from unittest.mock import patch

import pytest
from django_q.models import Schedule

from groceries.scheduled_tasks import run_daily_running_low_sync


@pytest.mark.django_db
def test_daily_running_low_schedule_cron_9am_santiago():
    row = Schedule.objects.get(name="groceries_daily_running_low_sync")
    assert row.schedule_type == Schedule.CRON
    assert row.cron == "0 9 * * *"


@pytest.mark.django_db
@patch("groceries.scheduled_tasks.services.sync_running_low_flags_for_all_users")
def test_run_daily_running_low_sync_delegates(mock_sync):
    mock_sync.return_value = 3
    assert run_daily_running_low_sync() == 3
    mock_sync.assert_called_once_with()
