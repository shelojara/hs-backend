from unittest.mock import patch

import pytest
from django.test import override_settings
from django_q.models import Schedule

from pagechecker.models import Page
from pagechecker.scheduled_tasks import (
    enqueue_daily_report_jobs,
    run_daily_page_check_dispatch,
    run_scheduled_page_check,
)
from pagechecker.services import page_ids_due_for_scheduled_check


@pytest.mark.django_db
def test_page_ids_due_for_scheduled_check_all_daily_flag_pages():
    p_a = Page.objects.create(
        url="https://example.com/daily-a",
        should_report_daily=True,
    )
    p_b = Page.objects.create(
        url="https://example.com/daily-b",
        should_report_daily=True,
    )
    p_off = Page.objects.create(
        url="https://example.com/no-daily",
        should_report_daily=False,
    )

    ids = page_ids_due_for_scheduled_check()
    assert set(ids) == {p_a.id, p_b.id}
    assert p_off.id not in ids


@pytest.mark.django_db
@patch("pagechecker.scheduled_tasks.async_task")
def test_run_daily_page_check_dispatch_enqueues_per_page(mock_async):
    p1 = Page.objects.create(
        url="https://example.com/dispatch-a",
        should_report_daily=True,
        last_checked_at=None,
    )
    p2 = Page.objects.create(
        url="https://example.com/dispatch-b",
        should_report_daily=True,
        last_checked_at=None,
    )

    with patch(
        "pagechecker.scheduled_tasks.services.page_ids_due_for_scheduled_check"
    ) as mock_ids:
        mock_ids.return_value = [p1.id, p2.id]
        out = run_daily_page_check_dispatch()

    assert out == [p1.id, p2.id]
    assert mock_async.call_count == 2
    mock_async.assert_any_call(
        "pagechecker.scheduled_tasks.run_scheduled_page_check",
        p1.id,
        task_name=f"scheduled_page_check:{p1.id}",
    )
    mock_async.assert_any_call(
        "pagechecker.scheduled_tasks.run_scheduled_page_check",
        p2.id,
        task_name=f"scheduled_page_check:{p2.id}",
    )


@pytest.mark.django_db
def test_daily_dispatcher_schedule_cron_9am_santiago():
    row = Schedule.objects.get(name="daily_page_check_dispatcher")
    assert row.schedule_type == Schedule.CRON
    assert row.cron == "0 9 * * *"


@pytest.mark.django_db
@patch("pagechecker.scheduled_tasks.async_task")
@override_settings(TIME_ZONE="Europe/Berlin")
def test_run_daily_page_check_dispatch_noop_when_timezone_not_santiago(mock_async):
    Page.objects.create(
        url="https://example.com/daily-wrong-tz",
        should_report_daily=True,
    )
    assert run_daily_page_check_dispatch() == []
    mock_async.assert_not_called()


@pytest.mark.django_db
@patch("pagechecker.scheduled_tasks.async_task")
@override_settings(TIME_ZONE="Europe/Berlin")
def test_enqueue_daily_report_jobs_force_skips_timezone_guard(mock_async):
    p = Page.objects.create(
        url="https://example.com/daily-force",
        should_report_daily=True,
    )
    out = enqueue_daily_report_jobs(skip_time_zone_check=True)
    assert out == [p.id]
    mock_async.assert_called_once_with(
        "pagechecker.scheduled_tasks.run_scheduled_page_check",
        p.id,
        task_name=f"scheduled_page_check:{p.id}",
    )


@pytest.mark.django_db
@patch("pagechecker.scheduled_tasks.services.run_daily_report_for_page")
def test_run_scheduled_page_check_delegates_to_daily_report(mock_report):
    run_scheduled_page_check(42)
    mock_report.assert_called_once_with(42)
