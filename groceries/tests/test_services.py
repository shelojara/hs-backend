from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from groceries.gemini_service import MerchantProductInfo, RunningLowSuggestion
from groceries.models import Basket, Product
from groceries.schemas import ProductCandidateSchema
from groceries.services import (
    InvalidProductListCursorError,
    LIST_PURCHASED_BASKETS_LIMIT,
    NoOpenBasketError,
    add_product_to_basket,
    create_product_from_candidate,
    delete_product_from_basket,
    find_product_candidates,
    get_current_basket_with_products,
    basket_total_price,
    list_products,
    list_purchased_baskets,
    purchase_latest_open_basket,
    recheck_product_price,
    suggest_running_low_products,
)

User = get_user_model()


def _user(username: str = "u1", **kwargs):
    return User.objects.create_user(username=username, password="pw", **kwargs)


def _catalog_owner_user():
    """Stable user for catalog rows when test does not care which owner."""
    existing = User.objects.filter(username="_catalog_owner").first()
    if existing is not None:
        return existing
    return User.objects.create_user(username="_catalog_owner", password="pw")


def _catalog_product(name: str, *, owner=None) -> Product:
    """Insert catalog row (no Gemini). Stand-in for removed create_product()."""
    if owner is None:
        owner = _catalog_owner_user()
    return Product.objects.create(name=name.strip(), user=owner)


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
def test_find_product_candidates_returns_gemini_rows_no_db(_mock_candidates):
    assert Product.objects.count() == 0
    rows = find_product_candidates(query="  leche  ")
    assert len(rows) == 1
    assert rows[0].display_name == "Colún Leche Entera 1 L"
    assert Product.objects.count() == 0


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_merchant_product_candidates",
    side_effect=RuntimeError("no key"),
)
def test_find_product_candidates_returns_empty_when_gemini_unconfigured(_mock_candidates):
    assert find_product_candidates(query="milk") == []


@pytest.mark.django_db
def test_find_product_candidates_rejects_blank_query():
    with pytest.raises(ValueError, match="empty"):
        find_product_candidates(query="   ")


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_merchant_product_info",
    return_value=None,
)
def test_create_product_from_candidate_persists_without_gemini(_mock_gemini):
    u = _user()
    pid = create_product_from_candidate(
        candidate=ProductCandidateSchema(
            name="Colún Leche Entera 1 L",
            standard_name="Leche entera",
            brand="Colún",
            price=Decimal("2590"),
            format="1 L",
            emoji="🥛",
        ),
        user_id=u.pk,
    )
    row = Product.objects.get(pk=pid)
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
def test_create_product_from_candidate_sets_is_custom(_mock_gemini):
    u = _user()
    pid = create_product_from_candidate(
        candidate=ProductCandidateSchema(
            name="Custom item",
            standard_name="",
            brand="",
            price=Decimal("0"),
            format="",
            emoji="",
        ),
        user_id=u.pk,
        is_custom=True,
    )
    assert Product.objects.get(pk=pid).is_custom is True


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_merchant_product_info",
    return_value=None,
)
def test_create_product_from_candidate_assigns_user(_mock_gemini):
    u = _user()
    pid = create_product_from_candidate(
        candidate=ProductCandidateSchema(
            name="Owned item",
            standard_name="",
            brand="",
            price=Decimal("0"),
            format="",
            emoji="",
        ),
        user_id=u.pk,
    )
    row = Product.objects.get(pk=pid)
    assert row.user_id == u.pk


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_merchant_product_info",
    return_value=None,
)
def test_list_products_orders_by_purchase_count_then_name_and_paginates(_mock_gemini):
    owner = _catalog_owner_user()
    _catalog_product("Apple")
    _catalog_product("Banana")
    _catalog_product("Carrot")
    page1, cur = list_products(user_id=owner.pk, limit=2)
    assert [p.name for p in page1] == ["Apple", "Banana"]
    assert cur is not None
    page2, cur2 = list_products(user_id=owner.pk, limit=2, cursor=cur)
    assert [p.name for p in page2] == ["Carrot"]
    assert cur2 is None


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_merchant_product_info",
    return_value=None,
)
def test_list_products_orders_by_purchase_count_desc(_mock_gemini):
    owner = _catalog_owner_user()
    hi = _catalog_product("Often bought", owner=owner)
    Product.objects.filter(pk=hi.pk).update(purchase_count=5)
    lo = _catalog_product("Rare", owner=owner)
    Product.objects.filter(pk=lo.pk).update(purchase_count=1)
    mid = _catalog_product("Medium", owner=owner)
    Product.objects.filter(pk=mid.pk).update(purchase_count=3)
    items, _ = list_products(user_id=owner.pk, limit=10)
    assert [p.pk for p in items] == [hi.pk, mid.pk, lo.pk]


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_merchant_product_info",
    return_value=None,
)
def test_list_products_search_icontains_ordered_by_purchase_count_then_name(_mock_gemini):
    owner = _catalog_owner_user()
    flakes = _catalog_product("Whole oat flakes", owner=owner)
    milk = _catalog_product("Oat milk", owner=owner)
    _catalog_product("Rice milk", owner=owner)
    Product.objects.filter(pk=flakes.pk).update(purchase_count=2)
    Product.objects.filter(pk=milk.pk).update(purchase_count=1)
    items, _ = list_products(user_id=owner.pk, search="oat", limit=10)
    assert [i.name for i in items] == ["Whole oat flakes", "Oat milk"]


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_merchant_product_info",
    return_value=None,
)
def test_list_products_search_paginates_with_cursor(_mock_gemini):
    owner = _catalog_owner_user()
    milk = _catalog_product("Oat milk", owner=owner)
    bar = _catalog_product("Oat bar", owner=owner)
    flakes = _catalog_product("Whole oat flakes", owner=owner)
    Product.objects.filter(pk=bar.pk).update(purchase_count=2)
    Product.objects.filter(pk=milk.pk).update(purchase_count=1)
    Product.objects.filter(pk=flakes.pk).update(purchase_count=0)
    first, nxt = list_products(user_id=owner.pk, search="oat", limit=1)
    assert len(first) == 1
    assert first[0].name == "Oat bar"
    assert nxt is not None
    second, nxt2 = list_products(user_id=owner.pk, search="oat", limit=1, cursor=nxt)
    assert len(second) == 1
    assert second[0].name == "Oat milk"
    assert nxt2 is not None


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_merchant_product_info",
    return_value=None,
)
def test_list_products_rejects_mismatched_cursor(_mock_gemini):
    owner = _catalog_owner_user()
    _catalog_product("X")
    _catalog_product("Y")
    _, cur = list_products(user_id=owner.pk, limit=1)
    assert cur is not None
    with pytest.raises(InvalidProductListCursorError):
        list_products(user_id=owner.pk, search="x", cursor=cur)


@pytest.mark.django_db
def test_list_products_rejects_invalid_cursor():
    owner = _catalog_owner_user()
    with pytest.raises(InvalidProductListCursorError):
        list_products(user_id=owner.pk, cursor="not-a-token")


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_merchant_product_info",
    return_value=None,
)
def test_list_products_excludes_products_in_open_basket(_mock_gemini):
    u = _user()
    p_in = _catalog_product("In cart")
    p_out = _catalog_product("Not in cart")
    add_product_to_basket(product_id=p_in.pk, user_id=u.pk)
    items, _ = list_products(user_id=u.pk, limit=10)
    assert [i.pk for i in items] == [p_out.pk]


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_merchant_product_info",
    return_value=None,
)
def test_list_products_rejects_cursor_from_different_user_context(_mock_gemini):
    alice = _user(username="alice")
    bob = _user(username="bob")
    _catalog_product("A")
    _catalog_product("B")
    _, cur = list_products(user_id=alice.pk, limit=1)
    assert cur is not None
    with pytest.raises(InvalidProductListCursorError):
        list_products(user_id=bob.pk, limit=1, cursor=cur)


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_merchant_product_info_by_identity",
    return_value=MerchantProductInfo(
        display_name="Colún Leche 1 L",
        standard_name="Leche entera",
        brand="Colún",
        price=Decimal("2700"),
        format="1 L",
        emoji="🥛",
    ),
)
def test_recheck_product_price_updates_price_only(_mock_identity):
    owner = _catalog_owner_user()
    p = Product.objects.create(
        name="Old label",
        standard_name="Leche entera",
        brand="Colún",
        format="1 L",
        price=Decimal("100"),
        user=owner,
    )
    out = recheck_product_price(product_id=p.pk, user_id=owner.pk)
    assert out.pk == p.pk
    assert out.name == "Old label"
    assert out.standard_name == "Leche entera"
    assert out.brand == "Colún"
    assert out.format == "1 L"
    assert out.price == Decimal("2700.00")


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_merchant_product_info_by_identity",
    return_value=None,
)
def test_recheck_product_price_noop_when_gemini_returns_none(_mock_identity):
    owner = _catalog_owner_user()
    p = Product.objects.create(
        name="Keep",
        standard_name="Arroz",
        brand="",
        format="500 g",
        price=Decimal("500"),
        user=owner,
    )
    before = (p.name, p.price)
    out = recheck_product_price(product_id=p.pk, user_id=owner.pk)
    assert (out.name, out.price) == before


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_merchant_product_info_by_identity",
    return_value=None,
)
def test_recheck_product_price_raises_when_missing_product(_mock_identity):
    owner = _catalog_owner_user()
    with pytest.raises(Product.DoesNotExist):
        recheck_product_price(product_id=99999, user_id=owner.pk)


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_merchant_product_info_by_identity",
    return_value=None,
)
def test_recheck_product_price_raises_when_not_owner(_mock_identity):
    alice = _user("alice_id")
    bob = _user("bob_id")
    p = Product.objects.create(
        name="X",
        standard_name="Arroz",
        brand="B",
        format="1 kg",
        user=alice,
    )
    with pytest.raises(Product.DoesNotExist):
        recheck_product_price(product_id=p.pk, user_id=bob.pk)


@pytest.mark.django_db
def test_recheck_product_price_raises_when_standard_name_blank():
    owner = _catalog_owner_user()
    p = Product.objects.create(
        name="No std",
        standard_name="",
        brand="",
        format="",
        user=owner,
    )
    with pytest.raises(ValueError, match="standard_name"):
        recheck_product_price(product_id=p.pk, user_id=owner.pk)


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_merchant_product_info",
    return_value=None,
)
def test_add_product_to_basket_creates_basket_when_none_open(_mock_gemini):
    user = _user()
    pid = _catalog_product("Milk").pk
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
    pid_a = _catalog_product("A").pk
    pid_b = _catalog_product("B").pk
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
    p = _catalog_product("X").pk
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
    pid = _catalog_product("Milk").pk
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
    pid = _catalog_product("X").pk
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
    pid = _catalog_product("Y").pk
    Basket.objects.create(owner=user)
    delete_product_from_basket(product_id=pid, user_id=user.pk)
    assert (
        Basket.objects.get(owner=user, purchased_at__isnull=True).products.count() == 0
    )


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_merchant_product_info",
    return_value=None,
)
def test_delete_product_from_basket_raises_when_no_open_basket(_mock_gemini):
    user = _user()
    pid = _catalog_product("Z").pk
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
def test_get_current_basket_with_products_none_when_empty(_mock_gemini):
    user = _user()
    assert get_current_basket_with_products(user_id=user.pk) is None


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_merchant_product_info",
    return_value=None,
)
def test_get_current_basket_with_products_returns_newest_and_ordered_products(
    _mock_gemini,
):
    user = _user()
    pid_a = _catalog_product("Apple").pk
    pid_b = _catalog_product("Banana").pk
    older = Basket.objects.create(owner=user)
    newer = Basket.objects.create(owner=user)
    older.products.add(pid_b)
    newer.products.add(pid_a)
    out = get_current_basket_with_products(user_id=user.pk)
    assert out is not None
    assert out.pk == newer.pk
    assert [p.pk for p in out.products.all()] == [pid_a]


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_merchant_product_info",
    return_value=None,
)
def test_get_current_basket_with_products_includes_purchased(_mock_gemini):
    user = _user()
    pid = _catalog_product("Z").pk
    b = Basket.objects.create(owner=user, purchased_at=timezone.now())
    b.products.add(pid)
    out = get_current_basket_with_products(user_id=user.pk)
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
    pa = Product.objects.create(name="A", price=Decimal("1.50"), user=user)
    pb = Product.objects.create(name="B", price=Decimal("2.25"), user=user)
    b = Basket.objects.create(owner=user)
    b.products.add(pa, pb)
    b = get_current_basket_with_products(user_id=user.pk)
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
    b = get_current_basket_with_products(user_id=user.pk)
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
    p = Product.objects.create(name="Milk", user=user)
    newer.products.add(p)
    out = purchase_latest_open_basket(user_id=user.pk)
    assert out.pk == newer.pk
    newer.refresh_from_db()
    older.refresh_from_db()
    assert newer.purchased_at is not None
    assert older.purchased_at is None
    p.refresh_from_db()
    assert p.purchase_count == 1


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_merchant_product_info",
    return_value=None,
)
def test_purchase_latest_open_basket_increments_each_product_once(_mock_gemini):
    user = _user()
    b = Basket.objects.create(owner=user)
    a = Product.objects.create(name="A", user=user)
    c = Product.objects.create(name="C", user=user)
    b.products.add(a, c)
    purchase_latest_open_basket(user_id=user.pk)
    a.refresh_from_db()
    c.refresh_from_db()
    assert a.purchase_count == 1
    assert c.purchase_count == 1


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_merchant_product_info",
    return_value=None,
)
def test_second_purchase_increments_again(_mock_gemini):
    user = _user()
    p = Product.objects.create(name="Eggs", user=user)
    b1 = Basket.objects.create(owner=user)
    b1.products.add(p)
    purchase_latest_open_basket(user_id=user.pk)
    b2 = Basket.objects.create(owner=user)
    b2.products.add(p)
    purchase_latest_open_basket(user_id=user.pk)
    p.refresh_from_db()
    assert p.purchase_count == 2


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
    p = _catalog_product("Shared catalog item").pk
    add_product_to_basket(product_id=p, user_id=alice.pk)
    assert get_current_basket_with_products(user_id=bob.pk) is None
    ba = add_product_to_basket(product_id=p, user_id=bob.pk)
    assert ba.owner_id == bob.pk
    assert Basket.objects.filter(owner=alice, purchased_at__isnull=True).count() == 1
    assert Basket.objects.filter(owner=bob, purchased_at__isnull=True).count() == 1


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_merchant_product_info",
    return_value=None,
)
def test_list_purchased_baskets_empty(_mock_gemini):
    user = _user()
    assert list_purchased_baskets(user_id=user.pk) == []


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_merchant_product_info",
    return_value=None,
)
def test_list_purchased_baskets_excludes_open(_mock_gemini):
    user = _user()
    Basket.objects.create(owner=user)
    b2 = Basket.objects.create(owner=user, purchased_at=timezone.now())
    rows = list_purchased_baskets(user_id=user.pk)
    assert len(rows) == 1
    assert rows[0].pk == b2.pk


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_merchant_product_info",
    return_value=None,
)
def test_list_purchased_baskets_caps_at_five_newest_by_purchased_at(_mock_gemini):
    user = _user()
    base = timezone.now()
    created = []
    for i in range(LIST_PURCHASED_BASKETS_LIMIT + 1):
        b = Basket.objects.create(
            owner=user,
            purchased_at=base - timedelta(seconds=i),
        )
        created.append(b)
    rows = list_purchased_baskets(user_id=user.pk)
    assert len(rows) == LIST_PURCHASED_BASKETS_LIMIT
    # Newest purchase first: skip oldest (largest timedelta offset)
    assert [r.pk for r in rows] == [c.pk for c in created[:-1]]


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_merchant_product_info",
    return_value=None,
)
def test_list_purchased_baskets_isolated_per_user(_mock_gemini):
    alice = _user(username="alice2")
    bob = _user(username="bob2")
    Basket.objects.create(owner=alice, purchased_at=timezone.now())
    assert list_purchased_baskets(user_id=bob.pk) == []


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_merchant_product_info",
    return_value=None,
)
def test_suggest_running_low_empty_without_purchased_baskets(_mock_gemini):
    user = _user(username="noruns")
    assert suggest_running_low_products(user_id=user.pk) == []


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_merchant_product_info",
    return_value=None,
)
@patch(
    "groceries.services.gemini_service.suggest_running_low_from_purchase_history",
)
def test_suggest_running_low_calls_gemini_with_history(mock_suggest, _mock_info):
    mock_suggest.return_value = [
        RunningLowSuggestion(
            product_name="Leche",
            reason="Última compra hace tiempo.",
            urgency="medium",
        ),
    ]
    user = _user(username="runlow")
    milk = _catalog_product("Leche entera", owner=user)
    b = Basket.objects.create(owner=user, purchased_at=timezone.now())
    b.products.add(milk)

    out = suggest_running_low_products(user_id=user.pk)

    assert len(out) == 1
    assert out[0].product_name == "Leche"
    mock_suggest.assert_called_once()
    call_kw = mock_suggest.call_args.kwargs
    assert "history_markdown" in call_kw
    assert "Leche entera" in call_kw["history_markdown"]
    assert "Basket 1" in call_kw["history_markdown"]


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_merchant_product_info",
    return_value=None,
)
@patch(
    "groceries.services.gemini_service.suggest_running_low_from_purchase_history",
    side_effect=RuntimeError("no key"),
)
def test_suggest_running_low_returns_empty_when_gemini_unconfigured(
    _mock_suggest,
    _mock_info,
):
    user = _user(username="nokey")
    milk = _catalog_product("Leche", owner=user)
    b = Basket.objects.create(owner=user, purchased_at=timezone.now())
    b.products.add(milk)
    assert suggest_running_low_products(user_id=user.pk) == []
