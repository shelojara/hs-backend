from decimal import Decimal

from django.conf import settings
from django.db import models


class Product(models.Model):
    name = models.CharField(max_length=255)
    standard_name = models.CharField(max_length=255, blank=True, default="")
    brand = models.CharField(max_length=255, blank=True, default="")
    price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0"),
    )
    format = models.CharField(max_length=255, blank=True, default="")
    emoji = models.CharField(max_length=64, blank=True, default="")
    is_custom = models.BooleanField(default=False)
    purchase_count = models.PositiveIntegerField(default=0)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="products",
    )

    class Meta:
        ordering = ("name",)

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
    products = models.ManyToManyField(Product, related_name="baskets", blank=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"Basket({self.pk}) at {self.created_at}"


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
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)

    def __str__(self) -> str:
        return self.name
