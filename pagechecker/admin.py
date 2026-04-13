from django.contrib import admin

from pagechecker.models import Page, Snapshot


class SnapshotInline(admin.TabularInline):
    model = Snapshot
    extra = 0
    readonly_fields = ("created_at", "content", "html_content", "features")
    can_delete = False


@admin.register(Page)
class PageAdmin(admin.ModelAdmin):
    list_display = ("url", "title", "created_at", "last_checked_at")
    list_filter = ("created_at", "last_checked_at")
    search_fields = ("url", "title")
    readonly_fields = ("created_at",)
    inlines = (SnapshotInline,)


@admin.register(Snapshot)
class SnapshotAdmin(admin.ModelAdmin):
    list_display = ("page", "created_at")
    list_filter = ("created_at",)
    search_fields = ("page__url", "page__title", "content")
    readonly_fields = ("created_at",)
    raw_id_fields = ("page",)
