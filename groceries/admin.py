from django.contrib import admin

from groceries.models import Product


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "last_bought_at")
