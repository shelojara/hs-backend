from django.contrib import admin

from manga.models import MangaHiddenDirectory, MangaLibraryChapter, MangaLibrarySeries


@admin.register(MangaHiddenDirectory)
class MangaHiddenDirectoryAdmin(admin.ModelAdmin):
    list_display = ("rel_path",)
    search_fields = ("rel_path",)


class MangaLibraryChapterInline(admin.TabularInline):
    model = MangaLibraryChapter
    extra = 0
    readonly_fields = ("rel_path", "filename", "size_bytes", "in_dropbox")
    can_delete = False


@admin.register(MangaLibrarySeries)
class MangaLibrarySeriesAdmin(admin.ModelAdmin):
    list_display = ("name", "series_rel_path", "library_root", "scanned_at")
    list_filter = ("library_root",)
    search_fields = ("name", "series_rel_path", "library_root")
    readonly_fields = ("scanned_at",)
    inlines = (MangaLibraryChapterInline,)
