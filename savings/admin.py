from django.contrib import admin

from savings.models import Asset, Distribution, DistributionLine, Family, FamilyMembership


@admin.register(Family)
class FamilyAdmin(admin.ModelAdmin):
    list_display = ("id", "created_by", "created_at")


@admin.register(FamilyMembership)
class FamilyMembershipAdmin(admin.ModelAdmin):
    list_display = ("id", "family", "user", "joined_at")


@admin.register(Asset)
class AssetAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "scope",
        "family",
        "owner",
        "weight",
        "current_amount",
        "target_amount",
        "currency",
    )
    list_filter = ("scope", "currency")
    search_fields = ("name",)


@admin.register(Distribution)
class DistributionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "budget_amount",
        "currency",
        "scope",
        "family",
        "owner",
        "created_at",
    )
    list_filter = ("scope", "currency")
    date_hierarchy = "created_at"


@admin.register(DistributionLine)
class DistributionLineAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "distribution",
        "asset",
        "allocated_amount",
    )
