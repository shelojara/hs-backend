from django.contrib.auth import get_user_model

from groceries.models import Product

User = get_user_model()


def user(username: str = "u1", **kwargs):
    return User.objects.create_user(username=username, password="pw", **kwargs)


def catalog_owner_user():
    """Stable user for catalog rows when test does not care which owner."""
    existing = User.objects.filter(username="_catalog_owner").first()
    if existing is not None:
        return existing
    return User.objects.create_user(username="_catalog_owner", password="pw")


def catalog_product(name: str, *, owner=None) -> Product:
    """Insert catalog row (no Gemini). Stand-in for removed create_product()."""
    if owner is None:
        owner = catalog_owner_user()
    return Product.objects.create(name=name.strip(), user=owner)
