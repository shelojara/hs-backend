from __future__ import annotations

import posixpath

from django.conf import settings
from django.db import models


def series_category_for_rel_path(series_rel_path: str) -> str:
    """Parent directory basename under library root; empty when series sits at root or one level below."""
    parent = posixpath.dirname(series_rel_path)
    if not parent:
        return ""
    return posixpath.basename(parent)


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


class GoogleDriveBackupJobStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed"


class CbzConvertKind(models.TextChoices):
    MANGA = "manga", "Manga"
    MANHWA = "manhwa", "Manhwa"


class GoogleDriveBackupJob(models.Model):
    """Async upload of one local CBZ to Google Drive under configured root folder (default ``Manga``).

    Jobs are created per ``SeriesItem`` when backing up a whole ``Series``.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="manga_google_drive_backup_jobs",
    )
    manga_root = models.CharField(
        max_length=4096,
        help_text="Normalized absolute manga library root when job was created.",
    )
    series = models.ForeignKey(
        "Series",
        on_delete=models.PROTECT,
        related_name="google_drive_backup_jobs",
    )
    series_item_id = models.PositiveIntegerField(
        help_text="Primary key of SeriesItem to upload.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(
        max_length=16,
        choices=GoogleDriveBackupJobStatus.choices,
        default=GoogleDriveBackupJobStatus.PENDING,
        db_index=True,
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    failure_message = models.TextField(null=True, blank=True)
    google_drive_file_id = models.CharField(
        max_length=128,
        blank=True,
        default="",
        help_text="Drive file id after successful upload or when an existing file was reused.",
    )

    class Meta:
        ordering = ("-created_at", "-id")
        indexes = [
            models.Index(
                fields=["user_id", "manga_root", "series_id"],
                name="manga_gdrive_user_root_series",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"GoogleDriveBackupJob(item={self.series_item_id}, status={self.status}, user={self.user_id})"
        )


class GoogleDriveRestoreJobStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed"


class GoogleDriveRestoreJob(models.Model):
    """Async restore of one series from Google Drive backup (download CBZs into library)."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="manga_google_drive_restore_jobs",
    )
    manga_root = models.CharField(
        max_length=4096,
        help_text="Normalized absolute manga library root when job was created.",
    )
    series_name = models.CharField(
        max_length=1024,
        help_text="Series folder name under Drive ``Manga/<name>/`` (matches backup layout).",
    )
    category = models.CharField(
        max_length=1024,
        blank=True,
        default="",
        help_text="Library subdirectory under manga root; files go to ``<root>/<category>/<series_name>/``.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(
        max_length=16,
        choices=GoogleDriveRestoreJobStatus.choices,
        default=GoogleDriveRestoreJobStatus.PENDING,
        db_index=True,
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    failure_message = models.TextField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at", "-id")
        indexes = [
            models.Index(
                fields=["user_id", "manga_root"],
                name="manga_gdrive_restore_user_root",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"GoogleDriveRestoreJob(category={self.category!r}, series_name={self.series_name!r}, "
            f"status={self.status}, user={self.user_id})"
        )


class GoogleDriveApplicationCredentials(models.Model):
    """Singleton (pk=1): OAuth web client + refresh token for manga Drive backups.

    Prefer this over a service account when uploading to a personal Google account
    (Drive quota applies to the signed-in user). Connect via **Start Google OAuth**
    on the change page after saving client id and secret.
    """

    client_id = models.CharField(
        max_length=256,
        blank=True,
        default="",
        help_text="OAuth 2.0 Web client ID from Google Cloud Console.",
    )
    client_secret = models.TextField(
        blank=True,
        default="",
        help_text="OAuth 2.0 client secret.",
    )
    refresh_token = models.TextField(
        blank=True,
        default="",
        help_text="Obtained automatically after staff authorizes in the browser.",
    )
    access_token = models.TextField(
        blank=True,
        default="",
        help_text="Cached access token; refreshed when near expiry.",
    )
    access_token_expires_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="UTC expiry for access_token.",
    )
    token_uri = models.CharField(
        max_length=256,
        default="https://oauth2.googleapis.com/token",
    )
    browser_api_key = models.CharField(
        max_length=256,
        blank=True,
        default="",
        help_text=(
            "Browser API key for Google Picker (optional). Restrict this key by HTTP "
            "referrer in Google Cloud Console."
        ),
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Google Drive OAuth credentials"
        verbose_name_plural = "Google Drive OAuth credentials"

    def save(self, *args, **kwargs) -> None:
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get_solo(cls) -> GoogleDriveApplicationCredentials | None:
        return cls.objects.filter(pk=1).first()

    def __str__(self) -> str:
        return "Google Drive OAuth (singleton)"


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
    category = models.CharField(
        max_length=1024,
        blank=True,
        default="",
        db_index=True,
        help_text="Parent directory under library root (basename of dirname(series_rel_path)); empty at root.",
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
    mangabaka_search_snoozed_until = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        help_text=(
            "After MangaBaka title search found no confident match, next search allowed at this time (UTC)."
        ),
    )
    scanned_at = models.DateTimeField(auto_now=True)

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
        indexes = [
            models.Index(
                fields=["library_root", "category"],
                name="manga_series_root_category",
            ),
        ]

    def save(self, *args, **kwargs) -> None:
        self.category = series_category_for_rel_path(self.series_rel_path)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.name} ({self.series_rel_path or '.'})"


class SeriesInfo(models.Model):
    """MangaBaka metadata for a cached ``Series`` (description, rating, type); created only after a title match."""

    series = models.OneToOneField(
        Series,
        on_delete=models.CASCADE,
        related_name="series_info",
    )
    mangabaka_series_id = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="MangaBaka API series id when a confident title match was found.",
    )
    description = models.TextField(blank=True, default="")
    rating = models.IntegerField(
        null=True,
        blank=True,
        help_text="Raw MangaBaka ``rating`` field (see API docs).",
    )
    series_type = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="MangaBaka API ``type`` field from series detail (e.g. manga, manhwa).",
    )
    is_complete = models.BooleanField(
        default=False,
        db_index=True,
        help_text="When true, MangaBaka detail fetch succeeded and description/rating/type are current.",
    )
    synced_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When description/rating/type was last written from MangaBaka detail API.",
    )

    class Meta:
        verbose_name = "manga series info (MangaBaka)"
        verbose_name_plural = "manga series info (MangaBaka)"

    def __str__(self) -> str:
        return f"SeriesInfo(series_id={self.series_id}, mb_id={self.mangabaka_series_id})"


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
    is_converted = models.BooleanField(default=False)
    dropbox_uploaded_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When this CBZ was uploaded to Dropbox (app-side; null if never uploaded).",
    )
    is_backed_up = models.BooleanField(
        default=False,
        db_index=True,
        help_text="True after a Google Drive backup job completed for this file (upload or same-name+size skip).",
    )
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
