from django.contrib import admin
from django.utils.html import format_html

from manga.models import MangaHiddenDirectory, Series, SeriesItem


@admin.register(MangaHiddenDirectory)
class MangaHiddenDirectoryAdmin(admin.ModelAdmin):
    list_display = ("rel_path",)
    search_fields = ("rel_path",)


class SeriesItemInline(admin.TabularInline):
    model = SeriesItem
    extra = 0
    readonly_fields = ("rel_path", "filename", "size_bytes", "in_dropbox")
    can_delete = False


@admin.register(Series)
class SeriesAdmin(admin.ModelAdmin):
    list_display = ("cover_thumbnail", "name", "series_rel_path", "library_root", "scanned_at")
    list_filter = ("library_root",)
    search_fields = ("name", "series_rel_path", "library_root")
    readonly_fields = (
        "scanned_at",
        "cover_preview",
        "cover_image_base64",
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
