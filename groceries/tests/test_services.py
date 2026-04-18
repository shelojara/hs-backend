from decimal import Decimal
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from groceries.gemini_service import MerchantProductInfo
from groceries.models import Basket, Product
from groceries.services import (
    InvalidProductListCursorError,
    NoOpenBasketError,
    ProductNameConflict,
    add_product_to_basket,
    create_product,
    create_product_from_merchant_info,
    delete_product_from_basket,
    find_products,
    get_latest_basket_with_products,
    basket_total_price,
    list_products,
    purchase_latest_open_basket,
    recheck_product_from_gemini,
)

User = get_user_model()


def _user(username: str = "u1", **kwargs):
    return User.objects.create_user(username=username, password="pw", **kwargs)


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_merchant_product_info",
    return_value=None,
)
def test_create_product_persists_and_returns_id(_mock_gemini):
    pid = create_product(name="  Oat milk  ")
    row = Product.objects.get(pk=pid)
    assert row.pk == pid
    assert row.name == "Oat milk"
    assert row.original_name == "Oat milk"


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_merchant_product_info",
    return_value=MerchantProductInfo(
        display_name="Oatly Leche de Avena 1 L",
        standard_name="Leche de avena",
        brand="Oatly",
        price=Decimal("3990"),
        format="1 L",
        emoji="🥛",
    ),
)
def test_create_product_stores_gemini_merchant_fields(_mock_gemini):
    pid = create_product(name="Avena")
    row = Product.objects.get(pk=pid)
    assert row.name == "Oatly Leche de Avena 1 L"
    assert row.original_name == "Avena"
    assert row.standard_name == "Leche de avena"
    assert row.brand == "Oatly"
    assert row.price == Decimal("3990.00")
    assert row.format == "1 L"
    assert row.emoji == "🥛"


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_merchant_product_info",
    return_value=None,
)
def test_create_product_leaves_price_zero_when_gemini_returns_none(_mock_gemini):
    pid = create_product(name="X")
    assert Product.objects.get(pk=pid).price == Decimal("0")


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_merchant_product_info",
    return_value=None,
)
def test_create_product_rejects_blank_name(_mock_gemini):
    with pytest.raises(ValueError, match="empty"):
        create_product(name="   ")


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_merchant_product_info",
    return_value=None,
)
def test_create_product_rejects_duplicate_name_case_insensitive(_mock_gemini):
    create_product(name="Oat milk")
    with pytest.raises(ProductNameConflict):
        create_product(name="  oat MILK  ")
    assert Product.objects.count() == 1


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_merchant_product_candidates",
    return_value=[
        MerchantProductInfo(
            display_name="Colún Leche Entera 1 L",
            standard_name="Leche entera",
            brand="Colún",
            price=Decimal("2590"),
            format="1 L",
            emoji="🥛",
        ),
    ],
)
def test_find_products_returns_gemini_rows_no_db(_mock_candidates):
    assert Product.objects.count() == 0
    rows = find_products(query="  leche  ")
    assert len(rows) == 1
    assert rows[0].display_name == "Colún Leche Entera 1 L"
    assert Product.objects.count() == 0


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_merchant_product_candidates",
    side_effect=RuntimeError("no key"),
)
def test_find_products_returns_empty_when_gemini_unconfigured(_mock_candidates):
    assert find_products(query="milk") == []


@pytest.mark.django_db
def test_find_products_rejects_blank_query():
    with pytest.raises(ValueError, match="empty"):
        find_products(query="   ")


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_merchant_product_info",
    return_value=None,
)
def test_create_product_from_merchant_info_persists_without_gemini(_mock_gemini):
    pid = create_product_from_merchant_info(
        query_name="  leche  ",
        info=MerchantProductInfo(
            display_name="Colún Leche Entera 1 L",
            standard_name="Leche entera",
            brand="Colún",
            price=Decimal("2590"),
            format="1 L",
            emoji="🥛",
        ),
    )
    row = Product.objects.get(pk=pid)
    assert row.original_name == "leche"
    assert row.name == "Colún Leche Entera 1 L"
    assert row.standard_name == "Leche entera"
    assert row.brand == "Colún"
    assert row.price == Decimal("2590.00")
    assert row.is_custom is False


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_merchant_product_info",
    return_value=None,
)
def test_create_product_from_merchant_info_sets_is_custom(_mock_gemini):
    pid = create_product_from_merchant_info(
        query_name="custom",
        info=MerchantProductInfo(
            display_name="Custom item",
            standard_name="",
            brand="",
            price=Decimal("0"),
            format="",
            emoji="",
        ),
        is_custom=True,
    )
    assert Product.objects.get(pk=pid).is_custom is True


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_merchant_product_info",
    return_value=None,
)
def test_create_product_from_merchant_info_uses_query_when_display_empty(_mock_gemini):
    pid = create_product_from_merchant_info(
        query_name="X",
        info=MerchantProductInfo(
            display_name="",
            standard_name="",
            brand="",
            price=Decimal("0"),
            format="",
            emoji="",
        ),
    )
    row = Product.objects.get(pk=pid)
    assert row.name == "X"
    assert row.original_name == "X"


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_merchant_product_info",
    return_value=None,
)
def test_create_product_from_merchant_info_rejects_duplicate_name(_mock_gemini):
    create_product_from_merchant_info(
        query_name="a",
        info=MerchantProductInfo(
            display_name="Same",
            standard_name="",
            brand="",
            price=Decimal("0"),
            format="",
            emoji="",
        ),
    )
    with pytest.raises(ProductNameConflict):
        create_product_from_merchant_info(
            query_name="b",
            info=MerchantProductInfo(
                display_name="same",
                standard_name="",
                brand="",
                price=Decimal("0"),
                format="",
                emoji="",
            ),
        )


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_merchant_product_info",
    return_value=None,
)
def test_list_products_orders_by_name_and_paginates(_mock_gemini):
    create_product(name="Apple")
    create_product(name="Banana")
    create_product(name="Carrot")
    page1, cur = list_products(limit=2)
    assert [p.name for p in page1] == ["Apple", "Banana"]
    assert cur is not None
    page2, cur2 = list_products(limit=2, cursor=cur)
    assert [p.name for p in page2] == ["Carrot"]
    assert cur2 is None


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_merchant_product_info",
    return_value=None,
)
def test_list_products_search_icontains_ordered_by_name(_mock_gemini):
    create_product(name="Oat milk")
    create_product(name="Whole oat flakes")
    create_product(name="Rice milk")
    items, _ = list_products(search="oat", limit=10)
    assert [i.name for i in items] == ["Oat milk", "Whole oat flakes"]


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_merchant_product_info",
    return_value=None,
)
def test_list_products_search_paginates_with_cursor(_mock_gemini):
    create_product(name="Oat milk")
    create_product(name="Oat bar")
    create_product(name="Whole oat flakes")
    first, nxt = list_products(search="oat", limit=1)
    assert len(first) == 1
    assert nxt is not None
    second, nxt2 = list_products(search="oat", limit=1, cursor=nxt)
    assert len(second) == 1
    assert second[0].name != first[0].name
    assert nxt2 is not None


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_merchant_product_info",
    return_value=None,
)
def test_list_products_rejects_mismatched_cursor(_mock_gemini):
    create_product(name="X")
    create_product(name="Y")
    _, cur = list_products(limit=1)
    assert cur is not None
    with pytest.raises(InvalidProductListCursorError):
        list_products(search="x", cursor=cur)


@pytest.mark.django_db
def test_list_products_rejects_invalid_cursor():
    with pytest.raises(InvalidProductListCursorError):
        list_products(cursor="not-a-token")


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_merchant_product_info",
    return_value=MerchantProductInfo(
        display_name="New Title",
        standard_name="Arroz",
        brand="B",
        price=Decimal("1000"),
        format="1 kg",
        emoji="🍚",
    ),
)
def test_recheck_product_from_gemini_updates_fields(_mock_gemini):
    pid = create_product(name="Old")
    out = recheck_product_from_gemini(product_id=pid)
    assert out.pk == pid
    assert out.name == "New Title"
    assert out.original_name == "Old"
    assert out.standard_name == "Arroz"
    assert out.brand == "B"
    assert out.price == Decimal("1000.00")
    assert out.format == "1 kg"
    assert out.emoji == "🍚"


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_merchant_product_info",
    return_value=None,
)
def test_recheck_product_from_gemini_noop_when_gemini_returns_none(_mock_gemini):
    pid = create_product(name="X")
    row = Product.objects.get(pk=pid)
    before = (row.name, row.brand, row.price)
    out = recheck_product_from_gemini(product_id=pid)
    assert (out.name, out.brand, out.price) == before


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_merchant_product_info",
    side_effect=RuntimeError("no key"),
)
def test_recheck_product_from_gemini_noop_when_gemini_key_missing(_mock_gemini):
    pid = create_product(name="Y")
    row = Product.objects.get(pk=pid)
    before = (row.name, row.brand)
    out = recheck_product_from_gemini(product_id=pid)
    assert (out.name, out.brand) == before


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_merchant_product_info",
    return_value=MerchantProductInfo(
        display_name="Taken",
        standard_name="",
        brand="",
        price=Decimal("0"),
        format="",
        emoji="",
    ),
)
def test_recheck_product_from_gemini_raises_when_display_name_conflicts(_mock_gemini):
    Product.objects.create(name="Taken", original_name="Taken")
    other = Product.objects.create(name="Other", original_name="Other")
    with pytest.raises(ProductNameConflict):
        recheck_product_from_gemini(product_id=other.pk)


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_merchant_product_info",
    return_value=None,
)
def test_recheck_product_from_gemini_raises_when_missing(_mock_gemini):
    with pytest.raises(Product.DoesNotExist):
        recheck_product_from_gemini(product_id=99999)


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_merchant_product_info",
    return_value=None,
)
def test_add_product_to_basket_creates_basket_when_none_open(_mock_gemini):
    user = _user()
    pid = create_product(name="Milk")
    basket = add_product_to_basket(product_id=pid, user_id=user.pk)
    assert basket.pk is not None
    assert basket.purchased_at is None
    assert list(basket.products.values_list("pk", flat=True)) == [pid]


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_merchant_product_info",
    return_value=None,
)
def test_add_product_to_basket_reuses_latest_open_basket(_mock_gemini):
    user = _user()
    pid_a = create_product(name="A")
    pid_b = create_product(name="B")
    older = Basket.objects.create(owner=user)
    newer = Basket.objects.create(owner=user)
    out = add_product_to_basket(product_id=pid_a, user_id=user.pk)
    assert out.pk == newer.pk
    assert set(newer.products.values_list("pk", flat=True)) == {pid_a}
    add_product_to_basket(product_id=pid_b, user_id=user.pk)
    newer.refresh_from_db()
    assert set(newer.products.values_list("pk", flat=True)) == {pid_a, pid_b}
    assert older.products.count() == 0


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_merchant_product_info",
    return_value=None,
)
def test_add_product_to_basket_skips_purchased_baskets(_mock_gemini):
    user = _user()
    p = create_product(name="X")
    open_b = Basket.objects.create(owner=user)
    Basket.objects.create(owner=user, purchased_at=timezone.now())
    out = add_product_to_basket(product_id=p, user_id=user.pk)
    assert out.pk == open_b.pk


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_merchant_product_info",
    return_value=None,
)
def test_add_product_to_basket_raises_when_product_missing(_mock_gemini):
    user = _user()
    with pytest.raises(Product.DoesNotExist):
        add_product_to_basket(product_id=99999, user_id=user.pk)


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_merchant_product_info",
    return_value=None,
)
def test_delete_product_from_basket_removes_line(_mock_gemini):
    user = _user()
    pid = create_product(name="Milk")
    add_product_to_basket(product_id=pid, user_id=user.pk)
    delete_product_from_basket(product_id=pid, user_id=user.pk)
    b = Basket.objects.get(owner=user, purchased_at__isnull=True)
    assert b.products.count() == 0


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_merchant_product_info",
    return_value=None,
)
def test_delete_product_from_basket_targets_latest_open_basket(_mock_gemini):
    user = _user()
    pid = create_product(name="X")
    older = Basket.objects.create(owner=user)
    newer = Basket.objects.create(owner=user)
    older.products.add(pid)
    delete_product_from_basket(product_id=pid, user_id=user.pk)
    newer.refresh_from_db()
    older.refresh_from_db()
    assert newer.products.count() == 0
    assert list(older.products.values_list("pk", flat=True)) == [pid]


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_merchant_product_info",
    return_value=None,
)
def test_delete_product_from_basket_noop_when_product_not_in_basket(_mock_gemini):
    user = _user()
    pid = create_product(name="Y")
    Basket.objects.create(owner=user)
    delete_product_from_basket(product_id=pid, user_id=user.pk)
    assert Basket.objects.get(owner=user, purchased_at__isnull=True).products.count() == 0


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_merchant_product_info",
    return_value=None,
)
def test_delete_product_from_basket_raises_when_no_open_basket(_mock_gemini):
    user = _user()
    pid = create_product(name="Z")
    Basket.objects.create(owner=user, purchased_at=timezone.now())
    with pytest.raises(NoOpenBasketError):
        delete_product_from_basket(product_id=pid, user_id=user.pk)


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_merchant_product_info",
    return_value=None,
)
def test_delete_product_from_basket_raises_when_product_missing(_mock_gemini):
    user = _user()
    Basket.objects.create(owner=user)
    with pytest.raises(Product.DoesNotExist):
        delete_product_from_basket(product_id=99999, user_id=user.pk)


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_merchant_product_info",
    return_value=None,
)
def test_get_latest_basket_with_products_none_when_empty(_mock_gemini):
    user = _user()
    assert get_latest_basket_with_products(user_id=user.pk) is None


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_merchant_product_info",
    return_value=None,
)
def test_get_latest_basket_with_products_returns_newest_and_ordered_products(_mock_gemini):
    user = _user()
    pid_a = create_product(name="Apple")
    pid_b = create_product(name="Banana")
    older = Basket.objects.create(owner=user)
    newer = Basket.objects.create(owner=user)
    older.products.add(pid_b)
    newer.products.add(pid_a)
    out = get_latest_basket_with_products(user_id=user.pk)
    assert out is not None
    assert out.pk == newer.pk
    assert [p.pk for p in out.products.all()] == [pid_a]


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_merchant_product_info",
    return_value=None,
)
def test_get_latest_basket_with_products_includes_purchased(_mock_gemini):
    user = _user()
    pid = create_product(name="Z")
    b = Basket.objects.create(owner=user, purchased_at=timezone.now())
    b.products.add(pid)
    out = get_latest_basket_with_products(user_id=user.pk)
    assert out is not None
    assert out.pk == b.pk
    assert list(out.products.values_list("pk", flat=True)) == [pid]


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_merchant_product_info",
    return_value=None,
)
def test_basket_total_price_sums_product_prices(_mock_gemini):
    user = _user()
    pa = Product.objects.create(name="A", price=Decimal("1.50"))
    pb = Product.objects.create(name="B", price=Decimal("2.25"))
    b = Basket.objects.create(owner=user)
    b.products.add(pa, pb)
    b = get_latest_basket_with_products(user_id=user.pk)
    assert b is not None
    assert basket_total_price(basket=b) == Decimal("3.75")


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_merchant_product_info",
    return_value=None,
)
def test_basket_total_price_empty_basket_zero(_mock_gemini):
    user = _user()
    Basket.objects.create(owner=user)
    b = get_latest_basket_with_products(user_id=user.pk)
    assert b is not None
    assert basket_total_price(basket=b) == Decimal("0")


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_merchant_product_info",
    return_value=None,
)
def test_purchase_latest_open_basket_sets_purchased_at(_mock_gemini):
    user = _user()
    older = Basket.objects.create(owner=user)
    newer = Basket.objects.create(owner=user)
    out = purchase_latest_open_basket(user_id=user.pk)
    assert out.pk == newer.pk
    newer.refresh_from_db()
    older.refresh_from_db()
    assert newer.purchased_at is not None
    assert older.purchased_at is None


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_merchant_product_info",
    return_value=None,
)
def test_purchase_latest_open_basket_skips_already_purchased(_mock_gemini):
    user = _user()
    open_b = Basket.objects.create(owner=user)
    Basket.objects.create(owner=user, purchased_at=timezone.now())
    out = purchase_latest_open_basket(user_id=user.pk)
    assert out.pk == open_b.pk
    open_b.refresh_from_db()
    assert open_b.purchased_at is not None


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_merchant_product_info",
    return_value=None,
)
def test_purchase_latest_open_basket_raises_when_none_open(_mock_gemini):
    user = _user()
    Basket.objects.create(owner=user, purchased_at=timezone.now())
    with pytest.raises(NoOpenBasketError):
        purchase_latest_open_basket(user_id=user.pk)


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_merchant_product_info",
    return_value=None,
)
def test_basket_operations_isolated_per_user(_mock_gemini):
    alice = _user(username="alice")
    bob = _user(username="bob")
    p = create_product(name="Shared catalog item")
    add_product_to_basket(product_id=p, user_id=alice.pk)
    assert get_latest_basket_with_products(user_id=bob.pk) is None
    ba = add_product_to_basket(product_id=p, user_id=bob.pk)
    assert ba.owner_id == bob.pk
    assert Basket.objects.filter(owner=alice, purchased_at__isnull=True).count() == 1
    assert Basket.objects.filter(owner=bob, purchased_at__isnull=True).count() == 1
