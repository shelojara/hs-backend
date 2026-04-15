"""Scheduled tasks executed by django-q2's qcluster worker."""

import logging

from pagechecker.models import Page
from pagechecker.services import check_page

logger = logging.getLogger(__name__)


def check_daily_pages() -> None:
    """Check every page flagged with *should_report_daily*."""
    pages = Page.objects.filter(should_report_daily=True)
    for page in pages:
        try:
            check_page(page.id)
            logger.info("Checked page %s (%s)", page.id, page.url)
        except Exception:
            logger.exception("Failed to check page %s (%s)", page.id, page.url)
