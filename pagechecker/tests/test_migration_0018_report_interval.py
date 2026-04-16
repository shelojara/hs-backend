"""Backfill behavior for 0018_page_report_interval."""

import importlib

import pytest
from django.apps import apps as django_apps

from pagechecker.models import Page, ReportInterval

m0018 = importlib.import_module("pagechecker.migrations.0018_page_report_interval")


@pytest.mark.django_db
def test_backfill_sets_report_interval_daily_for_flagged_pages():
    on = Page.objects.create(
        url="https://example.com/mig-on",
        should_report_daily=True,
    )
    off = Page.objects.create(
        url="https://example.com/mig-off",
        should_report_daily=False,
    )
    Page.objects.filter(id__in=[on.id, off.id]).update(report_interval=None)
    on.refresh_from_db()
    off.refresh_from_db()
    assert on.report_interval is None
    assert off.report_interval is None

    m0018.backfill_daily_report_interval(django_apps, None)

    on.refresh_from_db()
    off.refresh_from_db()
    assert on.report_interval == ReportInterval.DAILY
    assert off.report_interval is None
