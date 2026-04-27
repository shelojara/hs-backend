from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from groceries.gemini_service import (
    MerchantProductInfo,
    PreferredMerchantContext,
)
from groceries.models import (
    Basket,
    BasketProduct,
    Merchant,
    Product,
)
from groceries.schemas import ProductCandidateSchema
from groceries.tests.services.conftest import catalog_owner_user, catalog_product, user as _user
from groceries.services import (
    InvalidProductListCursorError,
    add_product_to_basket,
    create_product_from_candidate,
    delete_product,
    get_current_basket,
    list_products,
    mark_product_not_running_low,
    recheck_product_price,
    update_product,
)

User = get_user_model()


@pytest.mark.django_db
def test_create_product_from_candidate_persists_without_gemini():
    u = _user()
    pid = create_product_from_candidate(
        candidate=ProductCandidateSchema(
            name="Colún Leche Entera 1 L",
            standard_name="Leche entera",
            brand="Colún",
            price=Decimal("2590"),
            format="1 L",
            emoji="🥛",
            merchant="Lider",
        ),
        user_id=u.pk,
    )
    row = Product.objects.get(pk=pid)
    assert row.name == "Colún Leche Entera 1 L"
    assert row.standard_name == "Leche entera"
    assert row.brand == "Colún"
    assert row.price == Decimal("2590.00")
    assert row.is_custom is False
    assert row.quantity == 1


@pytest.mark.django_db
@patch("groceries.services.gemini_service.suggest_product_emoji", return_value="")
def test_create_product_from_candidate_sets_is_custom(_mock_emoji):
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
def test_create_product_from_candidate_null_price_stores_null():
    u = _user()
    pid = create_product_from_candidate(
        candidate=ProductCandidateSchema(
            name="No price yet",
            standard_name="",
            brand="",
            price=None,
            format="",
            emoji="",
        ),
        user_id=u.pk,
    )
    assert Product.objects.get(pk=pid).price is None


@pytest.mark.django_db
def test_create_product_from_candidate_assigns_user():
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
@patch("groceries.services.gemini_service.suggest_product_emoji", return_value="🌿")
def test_create_product_from_candidate_custom_blank_emoji_uses_gemini(mock_emoji):
    u = _user()
    pid = create_product_from_candidate(
        candidate=ProductCandidateSchema(
            name="Albahaca fresca",
            standard_name="Hierbas aromáticas",
            brand="",
            price=None,
            format="100 g",
            emoji="",
        ),
        user_id=u.pk,
        is_custom=True,
    )
    row = Product.objects.get(pk=pid)
    assert row.emoji == "🌿"
    mock_emoji.assert_called_once_with(
        name="Albahaca fresca",
        standard_name="Hierbas aromáticas",
        brand="",
        format="100 g",
    )


@pytest.mark.django_db
@patch("groceries.services.gemini_service.suggest_product_emoji")
def test_create_product_from_candidate_custom_nonempty_emoji_skips_gemini(mock_emoji):
    u = _user()
    pid = create_product_from_candidate(
        candidate=ProductCandidateSchema(
            name="Custom",
            standard_name="",
            brand="",
            price=None,
            format="",
            emoji="🧀",
        ),
        user_id=u.pk,
        is_custom=True,
    )
    assert Product.objects.get(pk=pid).emoji == "🧀"
    mock_emoji.assert_not_called()


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.suggest_product_emoji",
    side_effect=RuntimeError("no key"),
)
def test_create_product_from_candidate_custom_blank_emoji_gemini_unconfigured_empty(
    _mock_emoji,
):
    u = _user()
    pid = create_product_from_candidate(
        candidate=ProductCandidateSchema(
            name="X",
            standard_name="",
            brand="",
            price=None,
            format="",
            emoji="",
        ),
        user_id=u.pk,
        is_custom=True,
    )
    assert Product.objects.get(pk=pid).emoji == ""


@pytest.mark.django_db
@patch("groceries.services.gemini_service.suggest_product_emoji")
def test_create_product_from_candidate_non_custom_blank_emoji_skips_gemini(mock_emoji):
    u = _user()
    create_product_from_candidate(
        candidate=ProductCandidateSchema(
            name="Listed",
            standard_name="s",
            brand="",
            price=None,
            format="",
            emoji="",
        ),
        user_id=u.pk,
        is_custom=False,
    )
    mock_emoji.assert_not_called()


@pytest.mark.django_db
def test_update_product_persists_fields_without_gemini():
    u = _user()
    p = Product.objects.create(
        name="Old display",
        standard_name="Old std",
        brand="Old brand",
        price=Decimal("1.00"),
        format="500 ml",
        emoji="🥛",
        user=u,
    )
    out = update_product(
        product_id=p.pk,
        user_id=u.pk,
        standard_name="Leche entera",
        brand="Colún",
        format="1 L",
        price=Decimal("2590"),
        quantity=3,
        emoji="🐄",
    )
    assert out.pk == p.pk
    p.refresh_from_db()
    assert p.name == "Old display"
    assert p.standard_name == "Leche entera"
    assert p.brand == "Colún"
    assert p.format == "1 L"
    assert p.price == Decimal("2590.00")
    assert p.quantity == 3
    assert p.emoji == "🐄"


@pytest.mark.django_db
def test_update_product_blank_brand_stores_empty_string():
    u = _user()
    p = Product.objects.create(
        name="Item",
        standard_name="Std",
        brand="Was",
        price=Decimal("1.00"),
        format="1",
        emoji="🥛",
        user=u,
    )
    update_product(
        product_id=p.pk,
        user_id=u.pk,
        standard_name="Std",
        brand="   ",
        format="1",
        price=Decimal("1.00"),
        quantity=1,
        emoji="🥛",
    )
    p.refresh_from_db()
    assert p.brand == ""


@pytest.mark.django_db
def test_update_product_null_price_clears_price():
    u = _user()
    p = Product.objects.create(
        name="Item",
        standard_name="Std",
        brand="B",
        price=Decimal("5.00"),
        format="1",
        emoji="🧀",
        user=u,
    )
    update_product(
        product_id=p.pk,
        user_id=u.pk,
        standard_name="Std",
        brand="B",
        format="1",
        price=None,
        quantity=1,
        emoji="🧀",
    )
    p.refresh_from_db()
    assert p.price is None


@pytest.mark.django_db
@patch("groceries.services.gemini_service.suggest_product_emoji", return_value="🌿")
def test_update_product_custom_blank_emoji_uses_gemini(mock_emoji):
    u = _user()
    p = Product.objects.create(
        name="Herb mix",
        standard_name="Std",
        brand="",
        price=Decimal("1.00"),
        format="100 g",
        emoji="🥛",
        is_custom=True,
        user=u,
    )
    update_product(
        product_id=p.pk,
        user_id=u.pk,
        standard_name="Std",
        brand="",
        format="100 g",
        price=Decimal("1.00"),
        quantity=1,
        emoji="",
    )
    p.refresh_from_db()
    assert p.emoji == "🌿"
    mock_emoji.assert_called_once_with(
        name="Herb mix",
        standard_name="Std",
        brand="",
        format="100 g",
    )


@pytest.mark.django_db
@patch("groceries.services.gemini_service.suggest_product_emoji")
def test_update_product_custom_nonempty_emoji_skips_gemini(mock_emoji):
    u = _user()
    p = Product.objects.create(
        name="Item",
        standard_name="Std",
        brand="",
        price=Decimal("1.00"),
        format="1",
        emoji="🥛",
        is_custom=True,
        user=u,
    )
    update_product(
        product_id=p.pk,
        user_id=u.pk,
        standard_name="Std",
        brand="",
        format="1",
        price=Decimal("1.00"),
        quantity=1,
        emoji="🧀",
    )
    p.refresh_from_db()
    assert p.emoji == "🧀"
    mock_emoji.assert_not_called()


@pytest.mark.django_db
@patch("groceries.services.gemini_service.suggest_product_emoji", return_value="🌾")
def test_update_product_non_custom_blank_emoji_uses_gemini(mock_emoji):
    u = _user()
    p = Product.objects.create(
        name="Arroz",
        standard_name="Std",
        brand="",
        price=Decimal("1.00"),
        format="1 kg",
        emoji="🥛",
        is_custom=False,
        user=u,
    )
    update_product(
        product_id=p.pk,
        user_id=u.pk,
        standard_name="Std",
        brand="",
        format="1 kg",
        price=Decimal("1.00"),
        quantity=1,
        emoji="",
    )
    p.refresh_from_db()
    assert p.emoji == "🌾"
    mock_emoji.assert_called_once_with(
        name="Arroz",
        standard_name="Std",
        brand="",
        format="1 kg",
    )


@pytest.mark.django_db
@pytest.mark.parametrize("is_custom", [True, False])
@patch(
    "groceries.services.gemini_service.suggest_product_emoji",
    side_effect=RuntimeError("no key"),
)
def test_update_product_blank_emoji_gemini_unconfigured_empty(_mock_emoji, is_custom):
    u = _user()
    p = Product.objects.create(
        name="Item",
        standard_name="Std",
        brand="",
        price=Decimal("1.00"),
        format="1",
        emoji="🥛",
        is_custom=is_custom,
        user=u,
    )
    update_product(
        product_id=p.pk,
        user_id=u.pk,
        standard_name="Std",
        brand="",
        format="1",
        price=Decimal("1.00"),
        quantity=1,
        emoji="",
    )
    p.refresh_from_db()
    assert p.emoji == ""


@pytest.mark.django_db
def test_update_product_raises_when_wrong_user():
    u1 = _user(username="a")
    u2 = _user(username="b")
    p = Product.objects.create(name="X", user=u1)
    with pytest.raises(Product.DoesNotExist):
        update_product(
            product_id=p.pk,
            user_id=u2.pk,
            standard_name="",
            brand="",
            format="",
            price=Decimal("0"),
            quantity=1,
            emoji="",
        )


@pytest.mark.django_db
def test_delete_product_soft_deletes_and_removes_from_open_basket_only():
    u = _user()
    p = Product.objects.create(name="Milk", user=u)
    basket = add_product_to_basket(product_id=p.pk, user_id=u.pk)
    delete_product(product_id=p.pk, user_id=u.pk)
    assert not Product.objects.filter(pk=p.pk).exists()
    gone = Product.all_objects.get(pk=p.pk)
    assert gone.deleted_at is not None
    assert not BasketProduct.objects.filter(
        basket_id=basket.pk,
        product_id=p.pk,
    ).exists()


@pytest.mark.django_db
def test_delete_product_keeps_lines_on_purchased_baskets():
    u = _user()
    p = Product.objects.create(name="Milk", user=u)
    old = Basket.objects.create(
        owner=u,
        purchased_at=timezone.now() - timedelta(days=2),
    )
    old.products.add(p)
    add_product_to_basket(product_id=p.pk, user_id=u.pk)
    open_b = get_current_basket(user_id=u.pk)
    assert open_b is not None
    delete_product(product_id=p.pk, user_id=u.pk)
    assert BasketProduct.objects.filter(basket_id=old.pk, product_id=p.pk).exists()
    assert not BasketProduct.objects.filter(
        basket_id=open_b.pk,
        product_id=p.pk,
    ).exists()


@pytest.mark.django_db
def test_delete_product_raises_when_wrong_user():
    u1 = _user(username="a")
    u2 = _user(username="b")
    p = Product.objects.create(name="X", user=u1)
    with pytest.raises(Product.DoesNotExist):
        delete_product(product_id=p.pk, user_id=u2.pk)


@pytest.mark.django_db
def test_list_products_orders_by_purchase_count_then_name_and_paginates():
    owner = catalog_owner_user()
    catalog_product("Apple")
    catalog_product("Banana")
    catalog_product("Carrot")
    page1, cur = list_products(user_id=owner.pk, limit=2)
    assert [p.name for p in page1] == ["Apple", "Banana"]
    assert cur is not None
    page2, cur2 = list_products(user_id=owner.pk, limit=2, cursor=cur)
    assert [p.name for p in page2] == ["Carrot"]
    assert cur2 is None


@pytest.mark.django_db
def test_list_products_orders_by_purchase_count_desc():
    owner = catalog_owner_user()
    hi = catalog_product("Often bought", owner=owner)
    Product.objects.filter(pk=hi.pk).update(purchase_count=5)
    lo = catalog_product("Rare", owner=owner)
    Product.objects.filter(pk=lo.pk).update(purchase_count=1)
    mid = catalog_product("Medium", owner=owner)
    Product.objects.filter(pk=mid.pk).update(purchase_count=3)
    items, _ = list_products(user_id=owner.pk, limit=10)
    assert [p.pk for p in items] == [hi.pk, mid.pk, lo.pk]


@pytest.mark.django_db
def test_list_products_running_low_first_then_purchase_count():
    owner = catalog_owner_user()
    hi = catalog_product("Often bought", owner=owner)
    Product.objects.filter(pk=hi.pk).update(purchase_count=5)
    lo = catalog_product("Rare", owner=owner)
    Product.objects.filter(pk=lo.pk).update(purchase_count=1, running_low=True)
    mid = catalog_product("Medium", owner=owner)
    Product.objects.filter(pk=mid.pk).update(purchase_count=3)
    items, _ = list_products(user_id=owner.pk, limit=10)
    assert [p.pk for p in items] == [lo.pk, hi.pk, mid.pk]


@pytest.mark.django_db
def test_list_products_search_rapidfuzz_orders_ratio_then_purchase_count():
    owner = catalog_owner_user()
    flakes = catalog_product("Whole oat flakes", owner=owner)
    milk = catalog_product("Oat milk", owner=owner)
    catalog_product("Oat bar", owner=owner)
    catalog_product("Rice milk", owner=owner)
    Product.objects.filter(pk=flakes.pk).update(purchase_count=2)
    Product.objects.filter(pk=milk.pk).update(purchase_count=1)
    items, _ = list_products(user_id=owner.pk, search="oat", limit=10)
    # WRatio ties; partial_ratio ties; ``ratio("oat", hay)`` orders bar > milk > flakes. Rice milk out.
    # ``running_low`` only breaks ties after fuzzy scores.
    assert [i.name for i in items] == ["Oat bar", "Oat milk", "Whole oat flakes"]


@pytest.mark.django_db
def test_list_products_search_running_low_after_identical_fuzzy_scores():
    """Same haystack + purchase_count → ``running_low`` then ``pk``."""
    owner = catalog_owner_user()
    a = catalog_product("Oat dup", owner=owner)
    b = catalog_product("Oat dup", owner=owner)
    Product.objects.filter(pk=a.pk).update(purchase_count=1)
    Product.objects.filter(pk=b.pk).update(purchase_count=1, running_low=True)
    items, _ = list_products(user_id=owner.pk, search="oat dup", limit=10)
    assert [i.pk for i in items] == [b.pk, a.pk]


@pytest.mark.django_db
def test_list_products_search_matches_brand():
    owner = catalog_owner_user()
    branded = catalog_product("Leche entera", owner=owner)
    Product.objects.filter(pk=branded.pk).update(brand="Colún")
    catalog_product("Arroz", owner=owner)
    items, _ = list_products(user_id=owner.pk, search="colún", limit=10)
    assert len(items) == 1
    assert items[0].pk == branded.pk


@pytest.mark.django_db
def test_list_products_search_matches_standard_name_when_display_name_differs():
    owner = catalog_owner_user()
    p = catalog_product("SKU-991", owner=owner)
    Product.objects.filter(pk=p.pk).update(standard_name="Whole milk 1L")
    catalog_product("Other item", owner=owner)
    items, _ = list_products(user_id=owner.pk, search="whole milk", limit=10)
    assert [i.pk for i in items] == [p.pk]


@pytest.mark.django_db
def test_list_products_search_accent_insensitive_on_name():
    owner = catalog_owner_user()
    cafe = catalog_product("Café instantáneo", owner=owner)
    catalog_product("Arroz", owner=owner)
    items, _ = list_products(user_id=owner.pk, search="cafe instantaneo", limit=10)
    assert [p.pk for p in items] == [cafe.pk]


@pytest.mark.django_db
def test_list_products_search_rapidfuzz_typo_still_matches():
    owner = catalog_owner_user()
    milk = catalog_product("Oat milk", owner=owner)
    catalog_product("Rice", owner=owner)
    items, _ = list_products(user_id=owner.pk, search="ot mlk", limit=10)
    assert [p.pk for p in items] == [milk.pk]


@pytest.mark.django_db
def test_list_products_search_matches_keyword_in_long_standard_name():
    """Full-string WRatio underrates substring matches on long fields; gate uses per-field best."""
    owner = catalog_owner_user()
    p = catalog_product("SKU long label", owner=owner)
    Product.objects.filter(pk=p.pk).update(
        standard_name="Organic fair trade whole milk 1 L vitamin enriched",
        brand="Colún",
    )
    catalog_product("Rice", owner=owner)
    items, _ = list_products(user_id=owner.pk, search="milk", limit=10)
    assert [i.pk for i in items] == [p.pk]


@pytest.mark.django_db
def test_list_products_search_paginates_with_cursor():
    owner = catalog_owner_user()
    milk = catalog_product("Oat milk", owner=owner)
    bar = catalog_product("Oat bar", owner=owner)
    flakes = catalog_product("Whole oat flakes", owner=owner)
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
def test_list_products_rejects_mismatched_cursor():
    owner = catalog_owner_user()
    catalog_product("X")
    catalog_product("Y")
    _, cur = list_products(user_id=owner.pk, limit=1)
    assert cur is not None
    with pytest.raises(InvalidProductListCursorError):
        list_products(user_id=owner.pk, search="x", cursor=cur)


@pytest.mark.django_db
def test_list_products_rejects_invalid_cursor():
    owner = catalog_owner_user()
    with pytest.raises(InvalidProductListCursorError):
        list_products(user_id=owner.pk, cursor="not-a-token")


@pytest.mark.django_db
def test_list_products_excludes_products_in_open_basket():
    u = _user()
    p_in = catalog_product("In cart", owner=u)
    p_out = catalog_product("Not in cart", owner=u)
    add_product_to_basket(product_id=p_in.pk, user_id=u.pk)
    items, _ = list_products(user_id=u.pk, limit=10)
    assert [i.pk for i in items] == [p_out.pk]


@pytest.mark.django_db
def test_list_products_excludes_soft_deleted():
    u = _user()
    alive = Product.objects.create(name="Keep", user=u)
    dead = Product.objects.create(name="Gone", user=u)
    delete_product(product_id=dead.pk, user_id=u.pk)
    items, _ = list_products(user_id=u.pk, limit=10)
    assert [i.pk for i in items] == [alive.pk]


@pytest.mark.django_db
def test_list_products_rejects_cursor_from_different_user_context():
    alice = _user(username="alice")
    bob = _user(username="bob")
    catalog_product("A", owner=alice)
    catalog_product("B", owner=alice)
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
        merchant="",
    ),
)
def test_recheck_product_price_updates_price_only(_mock_identity):
    owner = catalog_owner_user()
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
@patch("groceries.services.gemini_service.fetch_merchant_product_info_by_identity")
def test_recheck_product_price_passes_preferred_merchants(mock_identity):
    mock_identity.return_value = None
    owner = catalog_owner_user()
    Merchant.objects.create(
        user=owner,
        name="Unimarc",
        website="https://www.unimarc.cl/",
    )
    p = Product.objects.create(
        name="X",
        standard_name="Leche entera",
        brand="Colún",
        format="1 L",
        price=Decimal("100"),
        user=owner,
    )
    recheck_product_price(product_id=p.pk, user_id=owner.pk)
    mock_identity.assert_called_once()
    ctx = mock_identity.call_args.kwargs["preferred_merchants"]
    assert len(ctx) == 1
    assert ctx[0] == PreferredMerchantContext(
        name="Unimarc",
        website="https://www.unimarc.cl/",
    )


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_merchant_product_info_by_identity",
    return_value=None,
)
def test_recheck_product_price_noop_when_gemini_returns_none(_mock_identity):
    owner = catalog_owner_user()
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
    return_value=MerchantProductInfo(
        display_name="X",
        standard_name="Arroz",
        brand="",
        price=None,
        format="500 g",
        emoji="",
        merchant="",
    ),
)
def test_recheck_product_price_noop_when_merchant_price_null(_mock_identity):
    owner = catalog_owner_user()
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
    owner = catalog_owner_user()
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
    owner = catalog_owner_user()
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
@patch("groceries.services.gemini_service.fetch_merchant_product_info_by_identity")
def test_recheck_product_price_custom_uses_display_name_when_standard_name_blank(
    mock_identity,
):
    mock_identity.return_value = MerchantProductInfo(
        display_name="X",
        standard_name="",
        brand="",
        price=Decimal("1500"),
        format="",
        emoji="",
        merchant="",
    )
    owner = catalog_owner_user()
    p = Product.objects.create(
        name="Pan de pueblo 500 g",
        standard_name="",
        brand="",
        format="",
        price=Decimal("100"),
        is_custom=True,
        user=owner,
    )
    out = recheck_product_price(product_id=p.pk, user_id=owner.pk)
    mock_identity.assert_called_once()
    assert mock_identity.call_args.kwargs["standard_name"] == "Pan de pueblo 500 g"
    assert out.price == Decimal("1500.00")


@pytest.mark.django_db
def test_mark_product_not_running_low_clears_and_snoozes():
    owner = catalog_owner_user()
    p = Product.objects.create(
        name="Milk",
        user=owner,
        running_low=True,
    )
    before = timezone.now()
    mark_product_not_running_low(product_id=p.pk, user_id=owner.pk)
    p.refresh_from_db()
    assert not p.running_low
    assert p.running_low_snoozed_until is not None
    assert p.running_low_snoozed_until >= before + timedelta(days=6, hours=23)


@pytest.mark.django_db
def test_mark_product_not_running_low_raises_when_not_owner():
    alice = _user("alice_mnrl")
    bob = _user("bob_mnrl")
    p = Product.objects.create(name="X", user=alice)
    with pytest.raises(Product.DoesNotExist):
        mark_product_not_running_low(product_id=p.pk, user_id=bob.pk)
