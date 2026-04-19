"""django-q Schedule row for groceries daily running-low sync."""

from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from django_q.models import Schedule

from groceries.models import Product
from groceries.scheduled_tasks import run_daily_running_low_sync, run_running_low_sync_for_user

User = get_user_model()


@pytest.mark.django_db
def test_daily_running_low_schedule_cron_9am_santiago():
    row = Schedule.objects.get(name="groceries_daily_running_low_sync")
    assert row.schedule_type == Schedule.CRON
    assert row.cron == "0 9 * * *"


@pytest.mark.django_db
@override_settings(
    FLAGS={
        "RUNNING_LOW_SCHEDULED_SYNC": [
            {"condition": "boolean", "value": False},
        ],
    }
)
@patch("groceries.scheduled_tasks.async_task")
def test_run_daily_running_low_sync_skips_when_flag_disabled(mock_async):
    a = User.objects.create_user(username="sched_rl_off_a", password="pw")
    Product.objects.create(name="pa", user=a)

    out = run_daily_running_low_sync()
    assert out == []
    mock_async.assert_not_called()


@pytest.mark.django_db
@override_settings(
    FLAGS={
        "RUNNING_LOW_SCHEDULED_SYNC": [
            {"condition": "boolean", "value": True},
        ],
    }
)
@patch("groceries.scheduled_tasks.async_task")
def test_run_daily_running_low_sync_enqueues_per_user(mock_async):
    a = User.objects.create_user(username="sched_rl_a", password="pw")
    b = User.objects.create_user(username="sched_rl_b", password="pw")
    Product.objects.create(name="pa", user=a)
    Product.objects.create(name="pb", user=b)

    out = run_daily_running_low_sync()
    assert sorted(out) == sorted([a.pk, b.pk])
    assert mock_async.call_count == 2
    names = {c.kwargs.get("task_name") for c in mock_async.call_args_list}
    assert names == {
        f"groceries_running_low_sync:{a.pk}",
        f"groceries_running_low_sync:{b.pk}",
    }
    for c in mock_async.call_args_list:
        assert c.args[0] == "groceries.scheduled_tasks.run_running_low_sync_for_user"
        assert c.args[1] in (a.pk, b.pk)


@pytest.mark.django_db
@patch("groceries.scheduled_tasks.services.sync_running_low_flags_for_user")
def test_run_running_low_sync_for_user_delegates(mock_sync):
    u = User.objects.create_user(username="rl_one", password="pw")
    run_running_low_sync_for_user(u.pk)
    mock_sync.assert_called_once_with(user_id=u.pk)
