"""django-q2 tasks for manga library cache and async CBZ conversion."""

import logging

from manga import services

logger = logging.getLogger(__name__)


def run_manga_library_cache_refresh(library_id: int | None = None) -> None:
    """Periodic job: rescan manga library filesystem(s) and persist series/chapter rows.

    When *library_id* is set, only that library is synced (``SyncLibrary`` RPC).
    When omitted (django-q schedule), every ``MangaLibrary`` row is synced in order.
    """
    if library_id is not None:
        try:
            services.sync_manga_library_cache(library_id=library_id)
        except services.LibrarySyncAlreadyRunningError:
            logger.info(
                "manga library cache refresh skipped (another sync in progress; library_id=%s)",
                library_id,
            )
        return

    from manga.models import MangaLibrary

    for lib in MangaLibrary.objects.order_by("pk").iterator(chunk_size=50):
        try:
            services.sync_manga_library_cache(library_id=lib.pk)
        except services.LibrarySyncAlreadyRunningError:
            logger.info(
                "manga library cache refresh skipped (another sync in progress; stopped at library_id=%s)",
                lib.pk,
            )
            break


def run_cbz_convert_job(job_id: int) -> None:
    """django-q2 entrypoint for async CBZ convert + Dropbox upload."""
    services.run_cbz_convert_job(job_id=job_id)


def run_google_drive_backup_job(job_id: int) -> None:
    """django-q2 entrypoint for async CBZ upload to Google Drive."""
    services.run_google_drive_backup_job(job_id=job_id)


def run_google_drive_restore_job(job_id: int) -> None:
    """django-q2 entrypoint: download series CBZs from Google Drive into library."""
    services.run_google_drive_restore_job(job_id=job_id)


def run_manga_mangabaka_series_info_sync() -> None:
    """Periodic job: small batch MangaBaka metadata → ``SeriesInfo``."""
    services.sync_manga_series_info_from_mangabaka()
