from django.contrib import admin

from groceries.models import Basket, Merchant, Product


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "standard_name",
        "brand",
        "price",
        "format",
        "is_custom",
        "purchase_count",
    )


@admin.register(Basket)
class BasketAdmin(admin.ModelAdmin):
    list_display = ("id", "owner", "created_at", "purchased_at")
    filter_horizontal = ("products",)


@admin.register(Merchant)
class MerchantAdmin(admin.ModelAdmin):
    list_display = ("name", "website", "user", "favicon_url", "updated_at")
    list_filter = ("user",)
    search_fields = ("name", "website")
