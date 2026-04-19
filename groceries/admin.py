from django.contrib import admin

from groceries.models import Basket, Product


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
