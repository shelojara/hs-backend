from decimal import Decimal

from django.conf import settings
from django.db import models

# Default icon for new product searches (API + first result candidate row).
# Same glyph for new recipes until Gemini fills a dish-specific emoji.
SEARCH_DEFAULT_EMOJI = "\N{LEFT-POINTING MAGNIFYING GLASS}"


class SearchStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed"


class ActiveSearchManager(models.Manager):
    """Rows with ``deleted_at`` unset (not soft-deleted)."""

    def get_queryset(self):
        return super().get_queryset().filter(deleted_at__isnull=True)


class Search(models.Model):
    """Async Gemini product search job; ``result_candidates`` filled when completed."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="groceries_searches",
    )
    query = models.TextField()
    emoji = models.CharField(
        max_length=64,
        blank=True,
        default=SEARCH_DEFAULT_EMOJI,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(
        max_length=16,
        choices=SearchStatus.choices,
        default=SearchStatus.PENDING,
        db_index=True,
    )
    result_candidates = models.JSONField(default=list)
    completed_at = models.DateTimeField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    all_objects = models.Manager()
    objects = ActiveSearchManager()

    class Meta:
        ordering = ("-created_at", "-id")
        base_manager_name = "all_objects"
        default_manager_name = "objects"

    def __str__(self) -> str:
        return f"Search({self.query[:60]!r}…) status={self.status} user={self.user_id}"


class ActiveProductManager(models.Manager):
    """Catalog rows with ``deleted_at`` unset (not soft-deleted)."""

    def get_queryset(self):
        return super().get_queryset().filter(deleted_at__isnull=True)


class Product(models.Model):
    name = models.CharField(max_length=255)
    standard_name = models.CharField(max_length=255, blank=True, default="")
    brand = models.CharField(max_length=255, blank=True, default="")
    price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        default=Decimal("0"),
    )
    format = models.CharField(max_length=255, blank=True, default="")
    quantity = models.PositiveIntegerField(default=1)
    emoji = models.CharField(max_length=64, blank=True, default="")
    is_custom = models.BooleanField(default=False)
    purchase_count = models.PositiveIntegerField(default=0)
    running_low = models.BooleanField(default=False)
    running_low_snoozed_until = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When set, scheduled running-low sync skips re-flagging until this instant.",
    )
    deleted_at = models.DateTimeField(null=True, blank=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="products",
    )

    all_objects = models.Manager()
    objects = ActiveProductManager()

    class Meta:
        ordering = ("name",)
        base_manager_name = "all_objects"
        default_manager_name = "objects"

    def __str__(self) -> str:
        return self.name


class Basket(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="baskets",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    purchased_at = models.DateTimeField(null=True, blank=True)
    products = models.ManyToManyField(
        Product,
        related_name="baskets",
        blank=True,
        through="BasketProduct",
    )

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"Basket({self.pk}) at {self.created_at}"


class BasketProduct(models.Model):
    """Per-line flag: include in checkout (``purchase``) or defer to next open basket."""

    basket = models.ForeignKey(Basket, on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    purchase = models.BooleanField(default=True)

    class Meta:
        unique_together = ("basket", "product")

    def __str__(self) -> str:
        return f"BasketProduct(basket={self.basket_id}, product={self.product_id}, purchase={self.purchase})"


class RecipeGenerationStatus(models.TextChoices):
    """Async Gemini fill for *CreateRecipeFromGemini*; completed = normal saved recipe."""

    PENDING = "pending", "Pending"
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed"


class Recipe(models.Model):
    """User-owned saved recipe; ingredients and steps in related tables."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="recipes",
    )
    title = models.CharField(max_length=255)
    emoji = models.CharField(
        max_length=64,
        blank=True,
        default=SEARCH_DEFAULT_EMOJI,
    )
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    generation_status = models.CharField(
        max_length=16,
        choices=RecipeGenerationStatus.choices,
        default=RecipeGenerationStatus.COMPLETED,
        db_index=True,
    )
    generation_failed_at = models.DateTimeField(null=True, blank=True)
    generation_error_message = models.TextField(blank=True, default="")

    class Meta:
        ordering = ("-updated_at", "-id")

    def __str__(self) -> str:
        return self.title


class RecipeIngredient(models.Model):
    """One ingredient line for a recipe (ordered)."""

    recipe = models.ForeignKey(
        Recipe,
        on_delete=models.CASCADE,
        related_name="ingredients",
    )
    order = models.PositiveIntegerField(default=0)
    name = models.CharField(max_length=255)
    amount = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Optional quantity or measure (e.g. 2 cups, 1 tbsp).",
    )

    class Meta:
        ordering = ("recipe", "order", "id")

    def __str__(self) -> str:
        return f"{self.name} (recipe={self.recipe_id})"


class RecipeStep(models.Model):
    """One numbered cooking step for a recipe (ordered)."""

    recipe = models.ForeignKey(
        Recipe,
        on_delete=models.CASCADE,
        related_name="steps",
    )
    order = models.PositiveIntegerField(default=0)
    text = models.TextField()

    class Meta:
        ordering = ("recipe", "order", "id")

    def __str__(self) -> str:
        return f"Step {self.order} (recipe={self.recipe_id})"


class RecipeMessage(models.Model):
    """User message to recipe chat plus model reply; CASCADE with recipe."""

    recipe = models.ForeignKey(
        Recipe,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    user_message = models.TextField()
    assistant_answer = models.TextField()
    gemini_response_raw = models.TextField(
        blank=True,
        default="",
        help_text="Full model response text from Gemini (before structured parse).",
    )
    recipe_updated = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("recipe", "created_at", "id")

    def __str__(self) -> str:
        return f"RecipeMessage(recipe={self.recipe_id}, id={self.pk})"


class Merchant(models.Model):
    """User-preferred merchant (store) with optional resolved favicon URL."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="merchants",
    )
    name = models.CharField(max_length=255)
    website = models.URLField(max_length=2048)
    favicon_url = models.URLField(max_length=2048, blank=True, default="")
    preference_order = models.PositiveIntegerField(
        default=0,
        help_text="Lower = higher priority (first in preferred list).",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("preference_order", "pk")
        constraints = [
            models.UniqueConstraint(
                fields=("user", "preference_order"),
                name="groceries_merchant_user_preference_order_uniq",
            ),
        ]

    def __str__(self) -> str:
        return self.name
