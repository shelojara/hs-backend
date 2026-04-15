from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from django_q.models import Schedule

from pagechecker.models import Page
from pagechecker.scheduled_tasks import run_daily_page_check_dispatch
from pagechecker.services import page_ids_due_for_scheduled_check


@pytest.mark.django_db
def test_page_ids_due_for_scheduled_check_respects_flag_and_cutoff():
    ref = datetime(2024, 6, 15, 12, 0, 0, tzinfo=UTC)
    today_early = datetime(2024, 6, 15, 1, 0, 0, tzinfo=UTC)
    yesterday = datetime(2024, 6, 14, 23, 0, 0, tzinfo=UTC)

    p_never = Page.objects.create(
        url="https://example.com/daily-never-checked",
        should_report_daily=True,
        last_checked_at=None,
    )
    p_stale = Page.objects.create(
        url="https://example.com/daily-stale",
        should_report_daily=True,
        last_checked_at=yesterday,
    )
    p_fresh = Page.objects.create(
        url="https://example.com/daily-fresh",
        should_report_daily=True,
        last_checked_at=today_early,
    )
    Page.objects.create(
        url="https://example.com/no-daily",
        should_report_daily=False,
        last_checked_at=None,
    )

    ids = page_ids_due_for_scheduled_check(now=ref)
    assert set(ids) == {p_never.id, p_stale.id}
    assert p_fresh.id not in ids


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
def test_daily_dispatcher_schedule_created_by_migration():
    assert Schedule.objects.filter(name="daily_page_check_dispatcher").exists()
