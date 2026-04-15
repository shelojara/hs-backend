"""Tests for pagechecker.tasks (django-q2 scheduled tasks)."""

from unittest.mock import patch

import pytest

from pagechecker.models import Page
from pagechecker.tasks import check_daily_pages


@pytest.mark.django_db
class TestCheckDailyPages:
    def test_calls_check_page_for_flagged_pages(self):
        p1 = Page.objects.create(url="https://example.com/a", should_report_daily=True)
        p2 = Page.objects.create(url="https://example.com/b", should_report_daily=True)
        Page.objects.create(url="https://example.com/c", should_report_daily=False)

        with patch("pagechecker.tasks.check_page") as mock_check:
            check_daily_pages()

        called_ids = sorted(c.args[0] for c in mock_check.call_args_list)
        assert called_ids == sorted([p1.id, p2.id])

    def test_skips_when_no_pages_flagged(self):
        Page.objects.create(url="https://example.com/d", should_report_daily=False)

        with patch("pagechecker.tasks.check_page") as mock_check:
            check_daily_pages()

        mock_check.assert_not_called()

    def test_continues_on_individual_failure(self):
        Page.objects.create(url="https://example.com/e", should_report_daily=True)
        Page.objects.create(url="https://example.com/f", should_report_daily=True)

        call_count = 0

        def fail_first(page_id):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("network error")

        with patch("pagechecker.tasks.check_page", side_effect=fail_first):
            check_daily_pages()

        assert call_count == 2
