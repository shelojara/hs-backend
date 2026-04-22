from django.contrib import admin
from django.contrib import messages
from django.db import transaction
from django.db.models import Count

from groceries.models import Basket, BasketProduct, Merchant, Product, Search, SearchQueryKind


@admin.action(description="Merge selected baskets into one (same owner only)")
def merge_baskets(modeladmin, request, queryset) -> None:
    """Merge into the basket with the lowest pk; combines duplicate products (purchase=true if any)."""
    count = queryset.count()
    if count < 2:
        modeladmin.message_user(
            request,
            "Select at least two baskets to merge.",
            level=messages.ERROR,
        )
        return

    baskets = list(queryset.select_related("owner"))
    owners = {b.owner_id for b in baskets}
    if len(owners) > 1:
        modeladmin.message_user(
            request,
            "All selected baskets must belong to the same user.",
            level=messages.ERROR,
        )
        return

    target = min(baskets, key=lambda b: b.pk)
    others = [b for b in baskets if b.pk != target.pk]

    with transaction.atomic():
        for basket in others:
            for bp in basket.basketproduct_set.all():
                obj, created = BasketProduct.objects.get_or_create(
                    basket=target,
                    product=bp.product,
                    defaults={"purchase": bp.purchase},
                )
                if not created:
                    merged = obj.purchase or bp.purchase
                    if merged != obj.purchase:
                        obj.purchase = merged
                        obj.save(update_fields=["purchase"])
                # Else: line already on target, flags merged above when not created
            basket.delete()

    modeladmin.message_user(
        request,
        f"Merged {count} baskets into basket #{target.pk}.",
        level=messages.SUCCESS,
    )


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
        "deleted_at",
    )
    list_filter = (("deleted_at", admin.EmptyFieldListFilter),)
    show_full_result_count = False

    def get_queryset(self, request):
        return Product.all_objects.select_related("user")


@admin.register(Basket)
class BasketAdmin(admin.ModelAdmin):
    list_display = ("id", "owner", "basket_products_count", "created_at", "purchased_at")
    actions = (merge_baskets,)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.annotate(_basketproduct_count=Count("basketproduct", distinct=True))

    @admin.display(description="Products", ordering="_basketproduct_count")
    def basket_products_count(self, obj: Basket) -> int:
        return getattr(obj, "_basketproduct_count", 0)


@admin.register(BasketProduct)
class BasketProductAdmin(admin.ModelAdmin):
    list_display = ("id", "basket", "product", "purchase")
    list_filter = ("purchase",)
    search_fields = ("product__name",)


@admin.register(Search)
class SearchAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "status",
        "kind_display",
        "query_preview",
        "created_at",
        "completed_at",
    )
    list_filter = ("status", "kind")
    search_fields = ("query",)

    @admin.display(description="Kind")
    def kind_display(self, obj: Search) -> str:
        if not obj.kind:
            return "—"
        return SearchQueryKind(obj.kind).label

    @admin.display(description="Query")
    def query_preview(self, obj: Search) -> str:
        q = (obj.query or "").strip()
        return q[:80] + ("…" if len(q) > 80 else "")


@admin.register(Merchant)
class MerchantAdmin(admin.ModelAdmin):
    list_display = ("name", "website", "user", "favicon_url", "updated_at")
    list_filter = ("user",)
    search_fields = ("name", "website")
