import pytest

from groceries.models import Product
from groceries.services import ProductNameConflict, create_product


@pytest.mark.django_db
def test_create_product_persists_and_returns_id():
    pid = create_product(name="  Oat milk  ")
    assert pid == Product.objects.get(pk=pid).pk
    assert Product.objects.get(pk=pid).name == "Oat milk"


@pytest.mark.django_db
def test_create_product_rejects_blank_name():
    with pytest.raises(ValueError, match="empty"):
        create_product(name="   ")


@pytest.mark.django_db
def test_create_product_rejects_duplicate_name_case_insensitive():
    create_product(name="Oat milk")
    with pytest.raises(ProductNameConflict):
        create_product(name="  oat MILK  ")
    assert Product.objects.count() == 1
