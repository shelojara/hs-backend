import posixpath

from django.conf import settings
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


class CbzConvertJobStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed"


class CbzConvertKind(models.TextChoices):
    MANGA = "manga", "Manga"
    MANHWA = "manhwa", "Manhwa"


class CbzConvertJob(models.Model):
    """Async CBZ conversion (Dropbox upload); same lifecycle pattern as groceries ``Search``."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="manga_cbz_convert_jobs",
    )
    manga_root = models.CharField(
        max_length=4096,
        help_text="Normalized absolute manga library root when job was created.",
    )
    series = models.ForeignKey(
        "Series",
        on_delete=models.PROTECT,
        related_name="cbz_convert_jobs",
        help_text="Series containing series_item_id; denormalized for efficient job listing.",
    )
    series_item_id = models.PositiveIntegerField(
        help_text="Primary key of SeriesItem to convert.",
    )
    kind = models.CharField(
        max_length=16,
        choices=CbzConvertKind.choices,
        default=CbzConvertKind.MANGA,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(
        max_length=16,
        choices=CbzConvertJobStatus.choices,
        default=CbzConvertJobStatus.PENDING,
        db_index=True,
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    failure_message = models.TextField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at", "-id")
        indexes = [
            models.Index(
                fields=["user_id", "manga_root", "series_id"],
                name="manga_cbzjob_user_root_series",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"CbzConvertJob(item={self.series_item_id}, kind={self.kind}, "
            f"status={self.status}, user={self.user_id})"
        )


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
    cover_image_base64 = models.TextField(
        null=True,
        blank=True,
        help_text="First page of first CBZ in series (natural sort), standard base64.",
    )
    cover_image_mime_type = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="MIME type for decoded cover bytes (e.g. image/jpeg).",
    )
    item_count = models.PositiveIntegerField(
        default=0,
        help_text="Number of cached SeriesItem rows (CBZ files) for this series; set by library sync.",
    )
    scanned_at = models.DateTimeField(auto_now=True)

    @property
    def category(self) -> str:
        """Parent directory name under library root; empty at root or one level below root."""
        parent = posixpath.dirname(self.series_rel_path)
        if not parent:
            return ""
        return posixpath.basename(parent)

    class Meta:
        ordering = ("library_root", "name", "series_rel_path")
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
    cover_image_base64 = models.TextField(
        null=True,
        blank=True,
        help_text="First image page in this CBZ (natural sort), standard base64 JPEG thumb.",
    )
    cover_image_mime_type = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="MIME type for decoded cover bytes (e.g. image/jpeg).",
    )
    file_created_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=(
            "Best-effort filesystem birth/creation time for the CBZ when synced "
            "(platform-dependent; falls back to metadata change time)."
        ),
    )

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
