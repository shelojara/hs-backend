from unittest.mock import patch

import pytest
from django.utils import timezone

from groceries.gemini_service import LiderProductInfo
from groceries.models import Basket, Product
from groceries.services import (
    InvalidProductListCursorError,
    NoOpenBasketError,
    ProductNameConflict,
    add_product_to_basket,
    create_product,
    delete_product_from_basket,
    get_latest_basket_with_products,
    list_products,
    purchase_latest_open_basket,
    recheck_product_from_gemini,
)


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_lider_product_info",
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
    "groceries.services.gemini_service.fetch_lider_product_info",
    return_value=LiderProductInfo(
        display_name="Oatly Leche de Avena 1 L",
        brand="Oatly",
        price="$3.990",
        format="1 L",
        details="Leche de avena 1 L en lácteos.",
    ),
)
def test_create_product_stores_gemini_lider_details(_mock_gemini):
    pid = create_product(name="Avena")
    row = Product.objects.get(pk=pid)
    assert row.name == "Oatly Leche de Avena 1 L"
    assert row.original_name == "Avena"
    assert row.brand == "Oatly"
    assert row.price == "$3.990"
    assert row.format == "1 L"
    assert row.details == "Leche de avena 1 L en lácteos."


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_lider_product_info",
    return_value=None,
)
def test_create_product_leaves_details_empty_when_gemini_returns_none(_mock_gemini):
    pid = create_product(name="X")
    assert Product.objects.get(pk=pid).details == ""


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_lider_product_info",
    return_value=None,
)
def test_create_product_rejects_blank_name(_mock_gemini):
    with pytest.raises(ValueError, match="empty"):
        create_product(name="   ")


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_lider_product_info",
    return_value=None,
)
def test_create_product_rejects_duplicate_name_case_insensitive(_mock_gemini):
    create_product(name="Oat milk")
    with pytest.raises(ProductNameConflict):
        create_product(name="  oat MILK  ")
    assert Product.objects.count() == 1


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_lider_product_info",
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
    "groceries.services.gemini_service.fetch_lider_product_info",
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
    "groceries.services.gemini_service.fetch_lider_product_info",
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
    "groceries.services.gemini_service.fetch_lider_product_info",
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
    "groceries.services.gemini_service.fetch_lider_product_info",
    return_value=LiderProductInfo(
        display_name="New Title",
        brand="B",
        price="1000",
        format="1 kg",
        details="D",
    ),
)
def test_recheck_product_from_gemini_updates_fields(_mock_gemini):
    pid = create_product(name="Old")
    out = recheck_product_from_gemini(product_id=pid)
    assert out.pk == pid
    assert out.name == "New Title"
    assert out.original_name == "Old"
    assert out.brand == "B"
    assert out.price == "1000"
    assert out.format == "1 kg"
    assert out.details == "D"


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_lider_product_info",
    return_value=None,
)
def test_recheck_product_from_gemini_noop_when_gemini_returns_none(_mock_gemini):
    pid = create_product(name="X")
    row = Product.objects.get(pk=pid)
    before = (row.name, row.brand, row.details)
    out = recheck_product_from_gemini(product_id=pid)
    assert (out.name, out.brand, out.details) == before


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_lider_product_info",
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
    "groceries.services.gemini_service.fetch_lider_product_info",
    return_value=LiderProductInfo(
        display_name="Taken",
        brand="",
        price="",
        format="",
        details="",
    ),
)
def test_recheck_product_from_gemini_raises_when_display_name_conflicts(_mock_gemini):
    Product.objects.create(name="Taken", original_name="Taken")
    other = Product.objects.create(name="Other", original_name="Other")
    with pytest.raises(ProductNameConflict):
        recheck_product_from_gemini(product_id=other.pk)


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_lider_product_info",
    return_value=None,
)
def test_recheck_product_from_gemini_raises_when_missing(_mock_gemini):
    with pytest.raises(Product.DoesNotExist):
        recheck_product_from_gemini(product_id=99999)


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_lider_product_info",
    return_value=None,
)
def test_add_product_to_basket_creates_basket_when_none_open(_mock_gemini):
    pid = create_product(name="Milk")
    basket = add_product_to_basket(product_id=pid)
    assert basket.pk is not None
    assert basket.purchased_at is None
    assert list(basket.products.values_list("pk", flat=True)) == [pid]


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_lider_product_info",
    return_value=None,
)
def test_add_product_to_basket_reuses_latest_open_basket(_mock_gemini):
    pid_a = create_product(name="A")
    pid_b = create_product(name="B")
    older = Basket.objects.create()
    newer = Basket.objects.create()
    out = add_product_to_basket(product_id=pid_a)
    assert out.pk == newer.pk
    assert set(newer.products.values_list("pk", flat=True)) == {pid_a}
    add_product_to_basket(product_id=pid_b)
    newer.refresh_from_db()
    assert set(newer.products.values_list("pk", flat=True)) == {pid_a, pid_b}
    assert older.products.count() == 0


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_lider_product_info",
    return_value=None,
)
def test_add_product_to_basket_skips_purchased_baskets(_mock_gemini):
    p = create_product(name="X")
    open_b = Basket.objects.create()
    Basket.objects.create(purchased_at=timezone.now())
    out = add_product_to_basket(product_id=p)
    assert out.pk == open_b.pk


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_lider_product_info",
    return_value=None,
)
def test_add_product_to_basket_raises_when_product_missing(_mock_gemini):
    with pytest.raises(Product.DoesNotExist):
        add_product_to_basket(product_id=99999)


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_lider_product_info",
    return_value=None,
)
def test_delete_product_from_basket_removes_line(_mock_gemini):
    pid = create_product(name="Milk")
    add_product_to_basket(product_id=pid)
    delete_product_from_basket(product_id=pid)
    b = Basket.objects.get(purchased_at__isnull=True)
    assert b.products.count() == 0


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_lider_product_info",
    return_value=None,
)
def test_delete_product_from_basket_targets_latest_open_basket(_mock_gemini):
    pid = create_product(name="X")
    older = Basket.objects.create()
    newer = Basket.objects.create()
    older.products.add(pid)
    delete_product_from_basket(product_id=pid)
    newer.refresh_from_db()
    older.refresh_from_db()
    assert newer.products.count() == 0
    assert list(older.products.values_list("pk", flat=True)) == [pid]


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_lider_product_info",
    return_value=None,
)
def test_delete_product_from_basket_noop_when_product_not_in_basket(_mock_gemini):
    pid = create_product(name="Y")
    Basket.objects.create()
    delete_product_from_basket(product_id=pid)
    assert Basket.objects.get(purchased_at__isnull=True).products.count() == 0


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_lider_product_info",
    return_value=None,
)
def test_delete_product_from_basket_raises_when_no_open_basket(_mock_gemini):
    pid = create_product(name="Z")
    Basket.objects.create(purchased_at=timezone.now())
    with pytest.raises(NoOpenBasketError):
        delete_product_from_basket(product_id=pid)


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_lider_product_info",
    return_value=None,
)
def test_delete_product_from_basket_raises_when_product_missing(_mock_gemini):
    Basket.objects.create()
    with pytest.raises(Product.DoesNotExist):
        delete_product_from_basket(product_id=99999)


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_lider_product_info",
    return_value=None,
)
def test_get_latest_basket_with_products_none_when_empty(_mock_gemini):
    assert get_latest_basket_with_products() is None


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_lider_product_info",
    return_value=None,
)
def test_get_latest_basket_with_products_returns_newest_and_ordered_products(_mock_gemini):
    pid_a = create_product(name="Apple")
    pid_b = create_product(name="Banana")
    older = Basket.objects.create()
    newer = Basket.objects.create()
    older.products.add(pid_b)
    newer.products.add(pid_a)
    out = get_latest_basket_with_products()
    assert out is not None
    assert out.pk == newer.pk
    assert [p.pk for p in out.products.all()] == [pid_a]


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_lider_product_info",
    return_value=None,
)
def test_get_latest_basket_with_products_includes_purchased(_mock_gemini):
    pid = create_product(name="Z")
    b = Basket.objects.create(purchased_at=timezone.now())
    b.products.add(pid)
    out = get_latest_basket_with_products()
    assert out is not None
    assert out.pk == b.pk
    assert list(out.products.values_list("pk", flat=True)) == [pid]


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_lider_product_info",
    return_value=None,
)
def test_purchase_latest_open_basket_sets_purchased_at(_mock_gemini):
    older = Basket.objects.create()
    newer = Basket.objects.create()
    out = purchase_latest_open_basket()
    assert out.pk == newer.pk
    newer.refresh_from_db()
    older.refresh_from_db()
    assert newer.purchased_at is not None
    assert older.purchased_at is None


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_lider_product_info",
    return_value=None,
)
def test_purchase_latest_open_basket_skips_already_purchased(_mock_gemini):
    open_b = Basket.objects.create()
    Basket.objects.create(purchased_at=timezone.now())
    out = purchase_latest_open_basket()
    assert out.pk == open_b.pk
    open_b.refresh_from_db()
    assert open_b.purchased_at is not None


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_lider_product_info",
    return_value=None,
)
def test_purchase_latest_open_basket_raises_when_none_open(_mock_gemini):
    Basket.objects.create(purchased_at=timezone.now())
    with pytest.raises(NoOpenBasketError):
        purchase_latest_open_basket()
