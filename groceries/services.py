from django.db import IntegrityError

from groceries.models import Product


class ProductNameConflict(Exception):
    """Another product already uses this name (case-insensitive)."""

    def __init__(self, message: str = "A product with this name already exists.") -> None:
        super().__init__(message)


def create_product(*, name: str) -> int:
    normalized = name.strip()
    if not normalized:
        msg = "Product name must not be empty."
        raise ValueError(msg)
    if Product.objects.filter(name__iexact=normalized).exists():
        raise ProductNameConflict()
    try:
        product = Product.objects.create(name=normalized)
    except IntegrityError as exc:
        raise ProductNameConflict() from exc
    return product.pk
