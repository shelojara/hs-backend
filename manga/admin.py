from django.contrib import admin
from django.contrib import messages
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils.html import format_html

from manga.models import (
    CbzConvertJob,
    GoogleDriveApplicationCredentials,
    GoogleDriveBackupJob,
    GoogleDriveRestoreJob,
    MangaHiddenDirectory,
    MangaLibrary,
    Series,
    SeriesInfo,
    SeriesItem,
)
from manga.services import clean_series_item_filename_on_disk


class FilenameUnderscoreFilter(admin.SimpleListFilter):
    """Filter SeriesItem rows where ``.cbz`` basename contains ``_``."""

    title = "underscore in filename"
    parameter_name = "filename_underscore"

    def lookups(self, request, model_admin):
        return (
            ("yes", "Has underscore"),
            ("no", "No underscore"),
        )

    def queryset(self, request, queryset):
        val = self.value()
        if val == "yes":
            return queryset.filter(filename__contains="_")
        if val == "no":
            return queryset.exclude(filename__contains="_")
        return queryset


@admin.action(description="Clean CBZ filename (underscore rule; rename on disk)")
def clean_cbz_filename(modeladmin, request, queryset) -> None:
    ok = 0
    skipped = 0
    for item in queryset:
        old = item.rel_path
        try:
            updated = clean_series_item_filename_on_disk(item_id=item.pk)
        except ValueError as exc:
            modeladmin.message_user(
                request,
                f"{old}: {exc}",
                level=messages.ERROR,
            )
            continue
        if updated.rel_path == old:
            skipped += 1
        else:
            ok += 1
    if ok:
        modeladmin.message_user(request, f"Renamed {ok} file(s).", level=messages.SUCCESS)
    if skipped:
        modeladmin.message_user(
            request,
            f"Skipped {skipped} row(s) (already clean or rule did not apply).",
            level=messages.INFO,
        )


@admin.register(MangaLibrary)
class MangaLibraryAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "filesystem_path")
    search_fields = ("name", "filesystem_path")


@admin.register(GoogleDriveApplicationCredentials)
class GoogleDriveApplicationCredentialsAdmin(admin.ModelAdmin):
    """OAuth web client + stored refresh token (singleton)."""

    list_display = ("__str__", "has_refresh_token", "updated_at")
    readonly_fields = ("oauth_actions", "updated_at")

    fieldsets = (
        (
            None,
            {
                "fields": (
                    "oauth_actions",
                    "client_id",
                    "client_secret",
                    "refresh_token",
                    "access_token",
                    "access_token_expires_at",
                    "token_uri",
                    "updated_at",
                ),
            },
        ),
    )

    def has_add_permission(self, request):
        return not GoogleDriveApplicationCredentials.objects.filter(pk=1).exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        if GoogleDriveApplicationCredentials.objects.filter(pk=1).exists():
            return HttpResponseRedirect(
                reverse("admin:manga_googledriveapplicationcredentials_change", args=(1,)),
            )
        return super().changelist_view(request, extra_context=extra_context)

    @admin.display(description="OAuth", boolean=False)
    def oauth_actions(self, obj: GoogleDriveApplicationCredentials) -> str:
        if not obj or not obj.pk:
            return "Save once, then use buttons below."
        start = reverse("admin_manga_gdrive_oauth_start")
        return format_html(
            '<p><a class="button" href="{}">Start Google OAuth (sign in; offline consent)</a></p>'
            "<p>Add authorized redirect URI in Google Cloud Console: "
            "<code>…/admin/manga/googledriveoauth/callback/</code> (full URL of this site).</p>"
            "<p>Enable <strong>Google Drive API</strong> for this project.</p>",
            start,
        )

    @admin.display(description="Connected", boolean=True)
    def has_refresh_token(self, obj: GoogleDriveApplicationCredentials) -> bool:
        return bool((obj.refresh_token or "").strip())

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        if "refresh_token" in form.base_fields:
            form.base_fields["refresh_token"].widget.attrs["readonly"] = True
        if "access_token" in form.base_fields:
            form.base_fields["access_token"].widget.attrs["readonly"] = True
        return form


@admin.register(GoogleDriveBackupJob)
class GoogleDriveBackupJobAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "series",
        "series_item_id",
        "status",
        "google_drive_file_id",
        "created_at",
        "completed_at",
    )
    list_filter = ("status",)
    search_fields = ("manga_root", "failure_message", "google_drive_file_id")
    readonly_fields = ("created_at", "completed_at")


@admin.register(GoogleDriveRestoreJob)
class GoogleDriveRestoreJobAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "category",
        "series_name",
        "status",
        "created_at",
        "completed_at",
    )
    list_filter = ("status",)
    search_fields = ("manga_root", "series_name", "failure_message")
    readonly_fields = ("created_at", "completed_at")


@admin.register(CbzConvertJob)
class CbzConvertJobAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "series",
        "series_item_id",
        "kind",
        "status",
        "created_at",
        "completed_at",
    )
    list_filter = ("status", "kind")
    search_fields = ("manga_root", "failure_message")
    readonly_fields = ("created_at", "completed_at")


@admin.register(SeriesInfo)
class SeriesInfoAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "series",
        "mangabaka_series_id",
        "series_type",
        "rating",
        "is_complete",
        "synced_at",
    )
    list_filter = ("is_complete",)
    search_fields = ("description", "series__name")
    readonly_fields = ("synced_at",)


@admin.register(MangaHiddenDirectory)
class MangaHiddenDirectoryAdmin(admin.ModelAdmin):
    list_display = ("rel_path",)
    search_fields = ("rel_path",)


class SeriesItemInline(admin.TabularInline):
    model = SeriesItem
    extra = 0
    fields = (
        "rel_path",
        "filename",
        "size_bytes",
        "file_created_at",
        "is_converted",
        "is_backed_up",
        "dropbox_uploaded_at",
        "item_cover_preview",
    )
    readonly_fields = (
        "rel_path",
        "filename",
        "size_bytes",
        "file_created_at",
        "is_converted",
        "is_backed_up",
        "dropbox_uploaded_at",
        "item_cover_preview",
    )
    can_delete = False

    @admin.display(description="Item cover")
    def item_cover_preview(self, obj: SeriesItem) -> str:
        b64 = (obj.cover_image_base64 or "").strip()
        if not b64:
            return "—"
        mime = (obj.cover_image_mime_type or "").strip() or "image/jpeg"
        data_url = f"data:{mime};base64,{b64}"
        return format_html(
            '<img src="{}" alt="" style="max-height: 40px; max-width: 32px; object-fit: contain; vertical-align: middle;" />',
            data_url,
        )


@admin.register(SeriesItem)
class SeriesItemAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "series",
        "rel_path",
        "filename",
        "size_bytes",
        "is_converted",
        "is_backed_up",
    )
    list_filter = (FilenameUnderscoreFilter, "is_converted", "is_backed_up")
    search_fields = ("rel_path", "filename", "series__name")
    actions = (clean_cbz_filename,)


@admin.register(Series)
class SeriesAdmin(admin.ModelAdmin):
    exclude = ("cover_image_base64",)
    list_display = (
        "cover_thumbnail",
        "name",
        "category",
        "series_rel_path",
        "item_count",
        "library_root",
        "scanned_at",
    )
    list_filter = ("library_root", "category")
    search_fields = ("name", "series_rel_path", "library_root")
    readonly_fields = (
        "scanned_at",
        "mangabaka_search_snoozed_until",
        "cover_preview",
        "cover_image_mime_type",
    )
    inlines = (SeriesItemInline,)

    @admin.display(description="Cover")
    def cover_thumbnail(self, obj: Series) -> str:
        return self._cover_img_html(obj, max_h=48, max_w=64)

    @admin.display(description="Cover preview")
    def cover_preview(self, obj: Series) -> str:
        return self._cover_img_html(obj, max_h=400, max_w=320)

    @staticmethod
    def _cover_img_html(obj: Series, *, max_h: int, max_w: int) -> str:
        b64 = (obj.cover_image_base64 or "").strip()
        if not b64:
            return "—"
        mime = (obj.cover_image_mime_type or "").strip() or "image/jpeg"
        data_url = f"data:{mime};base64,{b64}"
        return format_html(
            '<img src="{}" alt="" style="max-height: {}px; max-width: {}px; object-fit: contain; vertical-align: middle;" />',
            data_url,
            max_h,
            max_w,
        )
