from django.db import models
from django.db.models import UniqueConstraint
from django.db.models.functions import Lower


class Product(models.Model):
    name = models.CharField(max_length=255)
    brand = models.CharField(max_length=255, blank=True, default="")
    price = models.CharField(max_length=128, blank=True, default="")
    format = models.CharField(max_length=255, blank=True, default="")
    details = models.TextField(blank=True, default="")

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


class Purchase(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    products = models.ManyToManyField(Product, related_name="purchases", blank=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"Purchase({self.pk}) at {self.created_at}"
