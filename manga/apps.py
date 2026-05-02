from django.apps import AppConfig


class MangaConfig(AppConfig):
    name = "manga"
    verbose_name = "Manga"

    def ready(self) -> None:
        import manga.signals  # noqa: F401
