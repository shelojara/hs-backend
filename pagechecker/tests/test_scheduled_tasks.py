from unittest.mock import patch

import pytest
from django.test import override_settings
from django_q.models import Schedule

from pagechecker.models import Page, ReportInterval
from pagechecker.scheduled_tasks import (
    enqueue_scheduled_daily_check_jobs,
    run_daily_page_check_dispatch,
    run_scheduled_page_check,
)
from pagechecker.services import page_ids_due_for_scheduled_check


@pytest.mark.django_db
def test_page_ids_due_for_scheduled_check_daily_interval_pages():
    p_a = Page.objects.create(
        url="https://example.com/daily-a",
        report_interval=ReportInterval.DAILY,
    )
    p_b = Page.objects.create(
        url="https://example.com/daily-b",
        report_interval=ReportInterval.DAILY,
    )
    p_off = Page.objects.create(
        url="https://example.com/no-daily",
        report_interval=ReportInterval.WEEKLY,
    )

    ids = page_ids_due_for_scheduled_check()
    assert set(ids) == {p_a.id, p_b.id}
    assert p_off.id not in ids


@pytest.mark.django_db
@patch("pagechecker.scheduled_tasks.async_task")
def test_run_daily_page_check_dispatch_enqueues_per_page(mock_async):
    p1 = Page.objects.create(
        url="https://example.com/dispatch-a",
        report_interval=ReportInterval.DAILY,
        last_checked_at=None,
    )
    p2 = Page.objects.create(
        url="https://example.com/dispatch-b",
        report_interval=ReportInterval.DAILY,
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
def test_enqueue_scheduled_daily_check_jobs_enqueues_regardless_of_time_zone(
    mock_async,
):
    p = Page.objects.create(
        url="https://example.com/daily-any-tz",
        report_interval=ReportInterval.DAILY,
    )
    out = enqueue_scheduled_daily_check_jobs()
    assert out == [p.id]
    mock_async.assert_called_once_with(
        "pagechecker.scheduled_tasks.run_scheduled_page_check",
        p.id,
        task_name=f"scheduled_page_check:{p.id}",
    )


@pytest.mark.django_db
@patch("pagechecker.scheduled_tasks.async_task")
@override_settings(TIME_ZONE="Europe/Berlin")
def test_run_daily_page_check_dispatch_enqueues_regardless_of_time_zone(mock_async):
    p = Page.objects.create(
        url="https://example.com/dispatch-any-tz",
        report_interval=ReportInterval.DAILY,
    )
    assert run_daily_page_check_dispatch() == [p.id]
    mock_async.assert_called_once_with(
        "pagechecker.scheduled_tasks.run_scheduled_page_check",
        p.id,
        task_name=f"scheduled_page_check:{p.id}",
    )


@pytest.mark.django_db
@patch("pagechecker.scheduled_tasks.services.check_page")
def test_run_scheduled_page_check_delegates_to_check_page(mock_check):
    run_scheduled_page_check(42)
    mock_check.assert_called_once_with(42)
