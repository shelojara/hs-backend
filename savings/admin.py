from django.contrib import admin

from savings.models import DistributionLine, DistributionSession, SavingsAsset


@admin.register(SavingsAsset)
class SavingsAssetAdmin(admin.ModelAdmin):
    list_display = ("name", "scope", "owner", "weight", "current_amount", "target_amount", "currency")
    list_filter = ("scope", "currency")
    search_fields = ("name",)


@admin.register(DistributionSession)
class DistributionSessionAdmin(admin.ModelAdmin):
    list_display = ("id", "budget_amount", "currency", "scope", "owner", "created_at")
    list_filter = ("scope", "currency")
    date_hierarchy = "created_at"


@admin.register(DistributionLine)
class DistributionLineAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "session",
        "asset_name_snapshot",
        "selected",
        "share_percent",
        "allocated_amount",
    )
    list_filter = ("selected",)
