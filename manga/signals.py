from django.conf import settings
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from manga.models import MangaHiddenDirectory


@receiver(post_save, sender=MangaHiddenDirectory)
@receiver(post_delete, sender=MangaHiddenDirectory)
def _invalidate_manga_directories_cache_on_hidden_change(
    sender,
    **kwargs,
) -> None:
    from manga.services import invalidate_manga_directories_cache

    invalidate_manga_directories_cache(manga_root=settings.MANGA_ROOT)
