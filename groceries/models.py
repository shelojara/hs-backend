from decimal import Decimal

from django.conf import settings
from django.db import models


class SearchStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed"


class Search(models.Model):
    """Async Gemini product search job; ``result_candidates`` filled when completed."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="groceries_searches",
    )
    query = models.TextField()
    status = models.CharField(
        max_length=16,
        choices=SearchStatus.choices,
        default=SearchStatus.PENDING,
        db_index=True,
    )
    result_candidates = models.JSONField(default=list)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-id",)

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
    emoji = models.CharField(max_length=64, blank=True, default="")
    is_custom = models.BooleanField(default=False)
    purchase_count = models.PositiveIntegerField(default=0)
    running_low = models.BooleanField(default=False)
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


class Whiteboard(models.Model):
    """Single persisted drawing per user (Groceries app)."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="groceries_whiteboard",
    )
    data = models.JSONField(default=list)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "whiteboard"

    def __str__(self) -> str:
        return f"Whiteboard(user={self.user_id})"


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
