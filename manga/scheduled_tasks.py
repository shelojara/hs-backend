"""django-q2 scheduled tasks for manga library cache."""

from django.conf import settings

from manga import services


def run_manga_library_cache_refresh() -> None:
    """Periodic job: rescan manga root and persist series/chapter rows."""
    services.sync_manga_library_cache(manga_root=settings.MANGA_ROOT)
