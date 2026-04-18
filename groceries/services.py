from groceries.models import Product


def create_product(*, name: str) -> int:
    normalized = name.strip()
    if not normalized:
        msg = "Product name must not be empty."
        raise ValueError(msg)
    product = Product.objects.create(name=normalized)
    return product.pk
