from django.db import models


def normalize_manga_hidden_rel_path(raw: str) -> str:
    """POSIX-style path under manga root: no leading slash, no empty segments, no '..' left."""
    s = (raw or "").strip().replace("\\", "/").strip("/")
    parts: list[str] = []
    for p in s.split("/"):
        if not p or p == ".":
            continue
        if p == "..":
            if parts:
                parts.pop()
            continue
        parts.append(p)
    return "/".join(parts)


class MangaHiddenDirectory(models.Model):
    """Directory path (relative to manga root) excluded from listings and library sync."""

    rel_path = models.CharField(
        max_length=1024,
        unique=True,
        help_text="Path under manga root using forward slashes, e.g. archive/old or Series Name",
    )

    class Meta:
        ordering = ("rel_path",)
        verbose_name = "hidden manga directory"
        verbose_name_plural = "hidden manga directories"

    def clean(self) -> None:
        from django.core.exceptions import ValidationError

        n = normalize_manga_hidden_rel_path(self.rel_path)
        if not n:
            raise ValidationError({"rel_path": "Enter a non-empty path (no ..-only segments)."})
        self.rel_path = n

    def save(self, *args, **kwargs) -> None:
        self.rel_path = normalize_manga_hidden_rel_path(self.rel_path)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.rel_path


class Series(models.Model):
    """Cached manga series: directory under ``library_root`` that directly contains ≥1 ``.cbz`` file."""

    library_root = models.CharField(
        max_length=4096,
        help_text="Normalized absolute path to manga library root when this row was written.",
    )
    series_rel_path = models.CharField(
        max_length=1024,
        help_text="Path under library root (POSIX-style); empty string means CBZs sit at library root.",
    )
    name = models.CharField(
        max_length=1024,
        help_text="Directory basename for this series (or library folder name when series_rel_path is empty).",
    )
    scanned_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("library_root", "series_rel_path")
        verbose_name = "manga series (cached)"
        verbose_name_plural = "manga series (cached)"
        constraints = [
            models.UniqueConstraint(
                fields=("library_root", "series_rel_path"),
                name="manga_mangalibraryseries_unique_root_path",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.series_rel_path or '.'})"


class SeriesItem(models.Model):
    """Cached CBZ: one file directly inside a series directory."""

    series = models.ForeignKey(
        Series,
        on_delete=models.CASCADE,
        related_name="items",
    )
    rel_path = models.CharField(
        max_length=1024,
        help_text="File path under library root (POSIX-style), e.g. MySeries/ch01.cbz",
    )
    filename = models.CharField(max_length=512)
    size_bytes = models.BigIntegerField(null=True, blank=True)
    in_dropbox = models.BooleanField(default=False)

    class Meta:
        ordering = ("series", "rel_path")
        verbose_name = "manga series item (cached)"
        verbose_name_plural = "manga series items (cached)"
        constraints = [
            models.UniqueConstraint(
                fields=("series", "rel_path"),
                name="manga_mangalibrarychapter_unique_series_relpath",
            ),
        ]

    def __str__(self) -> str:
        return self.rel_path
