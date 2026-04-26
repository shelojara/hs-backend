from django.contrib import admin
from django.contrib import messages
from django.db import transaction
from django.db.models import Count

from groceries.models import (
    Basket,
    BasketProduct,
    Merchant,
    Product,
    Recipe,
    RecipeIngredient,
    RecipeMessage,
    RecipeStep,
    Search,
)


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
        "running_low",
        "running_low_snoozed_until",
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
        "query_preview",
        "created_at",
        "completed_at",
    )
    list_filter = ("status",)
    search_fields = ("query",)

    @admin.display(description="Query")
    def query_preview(self, obj: Search) -> str:
        q = (obj.query or "").strip()
        return q[:80] + ("…" if len(q) > 80 else "")


class RecipeIngredientInline(admin.TabularInline):
    model = RecipeIngredient
    extra = 0
    fields = ("order", "name", "amount")


class RecipeStepInline(admin.TabularInline):
    model = RecipeStep
    extra = 0
    fields = ("order", "text")


@admin.register(Recipe)
class RecipeAdmin(admin.ModelAdmin):
    list_display = ("id", "emoji", "title", "user", "generation_status", "updated_at")
    search_fields = ("title", "notes")
    list_filter = ("user",)
    inlines = (RecipeIngredientInline, RecipeStepInline)


@admin.register(RecipeMessage)
class RecipeMessageAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "recipe",
        "user_message_preview",
        "assistant_answer_preview",
        "recipe_updated",
        "created_at",
    )
    list_filter = ("recipe_updated",)
    search_fields = ("user_message", "assistant_answer", "recipe__title")
    readonly_fields = ("created_at",)
    date_hierarchy = "created_at"
    show_full_result_count = False

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("recipe", "recipe__user")

    @admin.display(description="User message")
    def user_message_preview(self, obj: RecipeMessage) -> str:
        t = (obj.user_message or "").strip().replace("\n", " ")
        return t[:60] + ("…" if len(t) > 60 else "")

    @admin.display(description="Assistant")
    def assistant_answer_preview(self, obj: RecipeMessage) -> str:
        t = (obj.assistant_answer or "").strip().replace("\n", " ")
        return t[:60] + ("…" if len(t) > 60 else "")


@admin.register(Merchant)
class MerchantAdmin(admin.ModelAdmin):
    list_display = ("name", "website", "user", "favicon_url", "updated_at")
    list_filter = ("user",)
    search_fields = ("name", "website")
