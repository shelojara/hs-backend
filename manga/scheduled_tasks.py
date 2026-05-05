"""django-q2 tasks for manga library cache and async CBZ conversion."""

from django.conf import settings

from manga import services


def run_manga_library_cache_refresh() -> None:
    """Periodic job: rescan manga root and persist series/chapter rows."""
    services.sync_manga_library_cache(manga_root=settings.MANGA_ROOT)


def run_cbz_convert_job(job_id: int) -> None:
    """django-q2 entrypoint for async CBZ convert + Dropbox upload."""
    services.run_cbz_convert_job(job_id=job_id)


def run_google_drive_backup_job(job_id: int) -> None:
    """django-q2 entrypoint for async CBZ upload to Google Drive."""
    services.run_google_drive_backup_job(job_id=job_id)


def run_google_drive_restore_job(job_id: int) -> None:
    """django-q2 entrypoint: download series folder from Google Drive into local library."""
    services.run_google_drive_restore_job(job_id=job_id)


def run_manga_mangabaka_series_info_sync() -> None:
    """Periodic job: small batch MangaBaka metadata → ``SeriesInfo``."""
    services.sync_manga_series_info_from_mangabaka()
