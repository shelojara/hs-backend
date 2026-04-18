from django.conf import settings
from django.db import models
from django.db.models import UniqueConstraint
from django.db.models.functions import Lower


class Product(models.Model):
    name = models.CharField(max_length=255)
    original_name = models.CharField(max_length=255, blank=True, default="")
    standard_name = models.CharField(max_length=255, blank=True, default="")
    brand = models.CharField(max_length=255, blank=True, default="")
    price = models.CharField(max_length=128, blank=True, default="")
    format = models.CharField(max_length=255, blank=True, default="")
    details = models.TextField(blank=True, default="")
    emoji = models.CharField(max_length=64, blank=True, default="")

    class Meta:
        ordering = ("name",)
        constraints = [
            UniqueConstraint(
                Lower("name"),
                name="groceries_product_name_lower_uniq",
            ),
        ]

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
