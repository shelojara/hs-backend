"""Regression: migrate_sqlite_to_postgres uses dumpdata --all for soft-deleted FK targets."""

import json
import tempfile
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.utils import timezone

from groceries.models import Basket, BasketProduct, Product

User = get_user_model()


@pytest.mark.django_db
def test_dumpdata_all_includes_soft_deleted_product_referenced_by_basket_product():
    user = User.objects.create_user(username="u1", password="x")
    p = Product.objects.create(name="gone", user=user, deleted_at=timezone.now())
    basket = Basket.objects.create(owner=user)
    BasketProduct.objects.create(basket=basket, product=p, purchase=True)

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        path = Path(tmp.name)

    try:
        call_command(
            "dumpdata",
            "groceries",
            output=str(path),
            verbosity=0,
        )
        payload = json.loads(path.read_text())
        product_pks = {o["pk"] for o in payload if o["model"] == "groceries.product"}
        assert p.pk not in product_pks

        call_command(
            "dumpdata",
            "groceries",
            output=str(path),
            verbosity=0,
            use_base_manager=True,
        )
        payload_all = json.loads(path.read_text())
        product_pks_all = {o["pk"] for o in payload_all if o["model"] == "groceries.product"}
        assert p.pk in product_pks_all
    finally:
        path.unlink(missing_ok=True)
