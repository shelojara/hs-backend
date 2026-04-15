from django.contrib import admin

from pagechecker.models import Page, Question, Snapshot


class SnapshotInline(admin.TabularInline):
    model = Snapshot
    extra = 0
    readonly_fields = ("created_at", "html_content", "md_content")
    can_delete = False


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ("text_preview", "created_at")
    list_filter = ("created_at",)
    search_fields = ("text",)
    readonly_fields = ("created_at",)

    @admin.display(description="Text")
    def text_preview(self, obj: Question) -> str:
        s = obj.text
        return s[:120] + ("…" if len(s) > 120 else "")


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
    search_fields = ("page__url", "page__title", "md_content")
    readonly_fields = ("created_at",)
    raw_id_fields = ("page",)
