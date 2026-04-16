from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from django_q.models import Schedule

from pagechecker.models import Page, ReportInterval
from pagechecker.scheduled_tasks import (
    enqueue_daily_report_jobs,
    enqueue_monthly_report_jobs,
    enqueue_weekly_report_jobs,
    run_daily_page_check_dispatch,
    run_monthly_page_check_dispatch,
    run_weekly_page_check_dispatch,
    run_scheduled_page_check,
)
from pagechecker.services import (
    page_ids_due_for_monthly_scheduled_check,
    page_ids_due_for_scheduled_check,
    page_ids_due_for_weekly_scheduled_check,
)

User = get_user_model()


@pytest.mark.django_db
def test_page_ids_due_for_scheduled_check_daily_interval_only():
    owner = User.objects.create_user(username="sched_daily", password="pw")
    p_a = Page.objects.create(
        url="https://example.com/daily-a",
        report_interval=ReportInterval.DAILY,
        owner=owner,
    )
    p_b = Page.objects.create(
        url="https://example.com/daily-b",
        report_interval=ReportInterval.DAILY,
        owner=owner,
    )
    p_no_interval = Page.objects.create(
        url="https://example.com/no-interval",
        report_interval=None,
        owner=owner,
    )
    p_weekly = Page.objects.create(
        url="https://example.com/weekly",
        report_interval=ReportInterval.WEEKLY,
        owner=owner,
    )
    p_off = Page.objects.create(
        url="https://example.com/no-daily",
        report_interval=None,
        owner=owner,
    )

    ids = page_ids_due_for_scheduled_check()
    assert set(ids) == {p_a.id, p_b.id}
    assert p_no_interval.id not in ids
    assert p_weekly.id not in ids
    assert p_off.id not in ids


@pytest.mark.django_db
def test_page_ids_due_for_weekly_scheduled_check_weekly_interval_only():
    owner = User.objects.create_user(username="sched_weekly", password="pw")
    p_w = Page.objects.create(
        url="https://example.com/weekly-a",
        report_interval=ReportInterval.WEEKLY,
        owner=owner,
    )
    p_daily = Page.objects.create(
        url="https://example.com/daily-not-weekly",
        report_interval=ReportInterval.DAILY,
        owner=owner,
    )
    p_off = Page.objects.create(
        url="https://example.com/no-weekly",
        report_interval=None,
        owner=owner,
    )

    ids = page_ids_due_for_weekly_scheduled_check()
    assert ids == [p_w.id]
    assert p_daily.id not in ids
    assert p_off.id not in ids


@pytest.mark.django_db
def test_page_ids_due_for_monthly_scheduled_check_monthly_interval_only():
    owner = User.objects.create_user(username="sched_monthly", password="pw")
    p_m = Page.objects.create(
        url="https://example.com/monthly-a",
        report_interval=ReportInterval.MONTHLY,
        owner=owner,
    )
    p_daily = Page.objects.create(
        url="https://example.com/daily-not-monthly",
        report_interval=ReportInterval.DAILY,
        owner=owner,
    )
    p_off = Page.objects.create(
        url="https://example.com/no-monthly",
        report_interval=None,
        owner=owner,
    )

    ids = page_ids_due_for_monthly_scheduled_check()
    assert ids == [p_m.id]
    assert p_daily.id not in ids
    assert p_off.id not in ids


@pytest.mark.django_db
@patch("pagechecker.scheduled_tasks.async_task")
def test_run_daily_page_check_dispatch_enqueues_per_page(mock_async):
    owner = User.objects.create_user(username="dispatch_daily", password="pw")
    p1 = Page.objects.create(
        url="https://example.com/dispatch-a",
        report_interval=ReportInterval.DAILY,
        last_checked_at=None,
        owner=owner,
    )
    p2 = Page.objects.create(
        url="https://example.com/dispatch-b",
        report_interval=ReportInterval.DAILY,
        last_checked_at=None,
        owner=owner,
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
@patch("pagechecker.scheduled_tasks.async_task")
def test_run_weekly_page_check_dispatch_enqueues_per_page(mock_async):
    owner = User.objects.create_user(username="dispatch_weekly", password="pw")
    p1 = Page.objects.create(
        url="https://example.com/weekly-dispatch-a",
        report_interval=ReportInterval.WEEKLY,
        last_checked_at=None,
        owner=owner,
    )
    p2 = Page.objects.create(
        url="https://example.com/weekly-dispatch-b",
        report_interval=ReportInterval.WEEKLY,
        last_checked_at=None,
        owner=owner,
    )

    with patch(
        "pagechecker.scheduled_tasks.services.page_ids_due_for_weekly_scheduled_check"
    ) as mock_ids:
        mock_ids.return_value = [p1.id, p2.id]
        out = run_weekly_page_check_dispatch()

    assert out == [p1.id, p2.id]
    assert mock_async.call_count == 2
    mock_async.assert_any_call(
        "pagechecker.scheduled_tasks.run_scheduled_page_check",
        p1.id,
        task_name=f"scheduled_weekly_page_check:{p1.id}",
    )
    mock_async.assert_any_call(
        "pagechecker.scheduled_tasks.run_scheduled_page_check",
        p2.id,
        task_name=f"scheduled_weekly_page_check:{p2.id}",
    )


@pytest.mark.django_db
@patch("pagechecker.scheduled_tasks.async_task")
def test_run_monthly_page_check_dispatch_enqueues_per_page(mock_async):
    owner = User.objects.create_user(username="dispatch_monthly", password="pw")
    p1 = Page.objects.create(
        url="https://example.com/monthly-dispatch-a",
        report_interval=ReportInterval.MONTHLY,
        last_checked_at=None,
        owner=owner,
    )
    p2 = Page.objects.create(
        url="https://example.com/monthly-dispatch-b",
        report_interval=ReportInterval.MONTHLY,
        last_checked_at=None,
        owner=owner,
    )

    with patch(
        "pagechecker.scheduled_tasks.services.page_ids_due_for_monthly_scheduled_check"
    ) as mock_ids:
        mock_ids.return_value = [p1.id, p2.id]
        out = run_monthly_page_check_dispatch()

    assert out == [p1.id, p2.id]
    assert mock_async.call_count == 2
    mock_async.assert_any_call(
        "pagechecker.scheduled_tasks.run_scheduled_page_check",
        p1.id,
        task_name=f"scheduled_monthly_page_check:{p1.id}",
    )
    mock_async.assert_any_call(
        "pagechecker.scheduled_tasks.run_scheduled_page_check",
        p2.id,
        task_name=f"scheduled_monthly_page_check:{p2.id}",
    )


@pytest.mark.django_db
def test_daily_dispatcher_schedule_cron_9am_santiago():
    row = Schedule.objects.get(name="daily_page_check_dispatcher")
    assert row.schedule_type == Schedule.CRON
    assert row.cron == "0 9 * * *"


@pytest.mark.django_db
def test_weekly_dispatcher_schedule_cron_friday_930_santiago():
    row = Schedule.objects.get(name="weekly_page_check_dispatcher")
    assert row.schedule_type == Schedule.CRON
    assert row.cron == "30 9 * * 5"


@pytest.mark.django_db
def test_monthly_dispatcher_schedule_cron_5th_10am_santiago():
    row = Schedule.objects.get(name="monthly_page_check_dispatcher")
    assert row.schedule_type == Schedule.CRON
    assert row.cron == "0 10 5 * *"


@pytest.mark.django_db
@patch("pagechecker.scheduled_tasks.async_task")
@override_settings(TIME_ZONE="Europe/Berlin")
def test_enqueue_daily_report_jobs_enqueues_regardless_of_time_zone(mock_async):
    owner = User.objects.create_user(username="tz_daily", password="pw")
    p = Page.objects.create(
        url="https://example.com/daily-any-tz",
        report_interval=ReportInterval.DAILY,
        owner=owner,
    )
    out = enqueue_daily_report_jobs()
    assert out == [p.id]
    mock_async.assert_called_once_with(
        "pagechecker.scheduled_tasks.run_scheduled_page_check",
        p.id,
        task_name=f"scheduled_page_check:{p.id}",
    )


@pytest.mark.django_db
@patch("pagechecker.scheduled_tasks.async_task")
@override_settings(TIME_ZONE="Europe/Berlin")
def test_enqueue_weekly_report_jobs_enqueues_regardless_of_time_zone(mock_async):
    owner = User.objects.create_user(username="tz_weekly", password="pw")
    p = Page.objects.create(
        url="https://example.com/weekly-any-tz",
        report_interval=ReportInterval.WEEKLY,
        owner=owner,
    )
    out = enqueue_weekly_report_jobs()
    assert out == [p.id]
    mock_async.assert_called_once_with(
        "pagechecker.scheduled_tasks.run_scheduled_page_check",
        p.id,
        task_name=f"scheduled_weekly_page_check:{p.id}",
    )


@pytest.mark.django_db
@patch("pagechecker.scheduled_tasks.async_task")
@override_settings(TIME_ZONE="Europe/Berlin")
def test_enqueue_monthly_report_jobs_enqueues_regardless_of_time_zone(mock_async):
    owner = User.objects.create_user(username="tz_monthly", password="pw")
    p = Page.objects.create(
        url="https://example.com/monthly-any-tz",
        report_interval=ReportInterval.MONTHLY,
        owner=owner,
    )
    out = enqueue_monthly_report_jobs()
    assert out == [p.id]
    mock_async.assert_called_once_with(
        "pagechecker.scheduled_tasks.run_scheduled_page_check",
        p.id,
        task_name=f"scheduled_monthly_page_check:{p.id}",
    )


@pytest.mark.django_db
@patch("pagechecker.scheduled_tasks.async_task")
@override_settings(TIME_ZONE="Europe/Berlin")
def test_run_daily_page_check_dispatch_enqueues_regardless_of_time_zone(mock_async):
    owner = User.objects.create_user(username="tz_dispatch_d", password="pw")
    p = Page.objects.create(
        url="https://example.com/dispatch-any-tz",
        report_interval=ReportInterval.DAILY,
        owner=owner,
    )
    assert run_daily_page_check_dispatch() == [p.id]
    mock_async.assert_called_once_with(
        "pagechecker.scheduled_tasks.run_scheduled_page_check",
        p.id,
        task_name=f"scheduled_page_check:{p.id}",
    )


@pytest.mark.django_db
@patch("pagechecker.scheduled_tasks.async_task")
@override_settings(TIME_ZONE="Europe/Berlin")
def test_run_weekly_page_check_dispatch_enqueues_regardless_of_time_zone(mock_async):
    owner = User.objects.create_user(username="tz_dispatch_w", password="pw")
    p = Page.objects.create(
        url="https://example.com/weekly-dispatch-any-tz",
        report_interval=ReportInterval.WEEKLY,
        owner=owner,
    )
    assert run_weekly_page_check_dispatch() == [p.id]
    mock_async.assert_called_once_with(
        "pagechecker.scheduled_tasks.run_scheduled_page_check",
        p.id,
        task_name=f"scheduled_weekly_page_check:{p.id}",
    )


@pytest.mark.django_db
@patch("pagechecker.scheduled_tasks.async_task")
@override_settings(TIME_ZONE="Europe/Berlin")
def test_run_monthly_page_check_dispatch_enqueues_regardless_of_time_zone(mock_async):
    owner = User.objects.create_user(username="tz_dispatch_m", password="pw")
    p = Page.objects.create(
        url="https://example.com/monthly-dispatch-any-tz",
        report_interval=ReportInterval.MONTHLY,
        owner=owner,
    )
    assert run_monthly_page_check_dispatch() == [p.id]
    mock_async.assert_called_once_with(
        "pagechecker.scheduled_tasks.run_scheduled_page_check",
        p.id,
        task_name=f"scheduled_monthly_page_check:{p.id}",
    )


@pytest.mark.django_db
@patch("pagechecker.scheduled_tasks.services.run_daily_report_for_page")
def test_run_scheduled_page_check_delegates_to_daily_report(mock_report):
    run_scheduled_page_check(42)
    mock_report.assert_called_once_with(42)
