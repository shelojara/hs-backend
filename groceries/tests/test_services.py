from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from groceries.gemini_service import (
    MerchantProductInfo,
    PreferredMerchantContext,
    RecipeFullFromGemini,
    RecipeIngredientLine,
    RunningLowSuggestion,
)
from groceries.models import (
    SEARCH_DEFAULT_EMOJI,
    Basket,
    BasketProduct,
    Merchant,
    Product,
    Recipe,
    RecipeGenerationStatus,
    RecipeIngredient,
    RecipeMessage,
    RecipeStep,
)
from groceries.schemas import ProductCandidateSchema
from groceries.services import (
    InvalidProductListCursorError,
    InvalidRecipeListCursorError,
    LIST_PURCHASED_BASKETS_LIMIT,
    NoOpenBasketError,
    RecipeGenerationFailedError,
    add_product_to_basket,
    basket_product_lines,
    create_product_from_candidate,
    create_recipe_from_title_and_notes,
    get_recipe,
    run_recipe_gemini_job,
    update_recipe,
    delete_recipe,
    delete_product,
    delete_product_from_basket,
    get_current_basket,
    get_current_basket_with_products,
    list_products,
    list_recipe_messages,
    list_user_recipes,
    list_purchased_baskets,
    list_purchased_baskets_for_running_low,
    mark_product_not_running_low,
    recipe_ingredient_in_catalog_flags,
    recipe_chat_about_recipe,
    purchase_latest_open_basket,
    purchase_single_product,
    recalculate_product_purchase_counts_from_baskets,
    set_product_purchase_in_open_basket,
    recheck_product_price,
    running_low_sync_user_ids,
    sync_running_low_flags_for_user,
    update_product,
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
def test_list_products_orders_by_purchase_count_desc():
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
def test_list_products_running_low_first_then_purchase_count():
    owner = _catalog_owner_user()
    hi = _catalog_product("Often bought", owner=owner)
    Product.objects.filter(pk=hi.pk).update(purchase_count=5)
    lo = _catalog_product("Rare", owner=owner)
    Product.objects.filter(pk=lo.pk).update(purchase_count=1, running_low=True)
    mid = _catalog_product("Medium", owner=owner)
    Product.objects.filter(pk=mid.pk).update(purchase_count=3)
    items, _ = list_products(user_id=owner.pk, limit=10)
    assert [p.pk for p in items] == [lo.pk, hi.pk, mid.pk]


@pytest.mark.django_db
def test_list_products_search_rapidfuzz_orders_ratio_then_purchase_count():
    owner = _catalog_owner_user()
    flakes = _catalog_product("Whole oat flakes", owner=owner)
    milk = _catalog_product("Oat milk", owner=owner)
    _catalog_product("Oat bar", owner=owner)
    _catalog_product("Rice milk", owner=owner)
    Product.objects.filter(pk=flakes.pk).update(purchase_count=2)
    Product.objects.filter(pk=milk.pk).update(purchase_count=1)
    items, _ = list_products(user_id=owner.pk, search="oat", limit=10)
    # WRatio ties; partial_ratio ties; ``ratio("oat", hay)`` orders bar > milk > flakes. Rice milk out.
    # ``running_low`` only breaks ties after fuzzy scores.
    assert [i.name for i in items] == ["Oat bar", "Oat milk", "Whole oat flakes"]


@pytest.mark.django_db
def test_list_products_search_running_low_after_identical_fuzzy_scores():
    """Same haystack + purchase_count → ``running_low`` then ``pk``."""
    owner = _catalog_owner_user()
    a = _catalog_product("Oat dup", owner=owner)
    b = _catalog_product("Oat dup", owner=owner)
    Product.objects.filter(pk=a.pk).update(purchase_count=1)
    Product.objects.filter(pk=b.pk).update(purchase_count=1, running_low=True)
    items, _ = list_products(user_id=owner.pk, search="oat dup", limit=10)
    assert [i.pk for i in items] == [b.pk, a.pk]


@pytest.mark.django_db
def test_list_products_search_matches_brand():
    owner = _catalog_owner_user()
    branded = _catalog_product("Leche entera", owner=owner)
    Product.objects.filter(pk=branded.pk).update(brand="Colún")
    _catalog_product("Arroz", owner=owner)
    items, _ = list_products(user_id=owner.pk, search="colún", limit=10)
    assert len(items) == 1
    assert items[0].pk == branded.pk


@pytest.mark.django_db
def test_list_products_search_matches_standard_name_when_display_name_differs():
    owner = _catalog_owner_user()
    p = _catalog_product("SKU-991", owner=owner)
    Product.objects.filter(pk=p.pk).update(standard_name="Whole milk 1L")
    _catalog_product("Other item", owner=owner)
    items, _ = list_products(user_id=owner.pk, search="whole milk", limit=10)
    assert [i.pk for i in items] == [p.pk]


@pytest.mark.django_db
def test_list_products_search_accent_insensitive_on_name():
    owner = _catalog_owner_user()
    cafe = _catalog_product("Café instantáneo", owner=owner)
    _catalog_product("Arroz", owner=owner)
    items, _ = list_products(user_id=owner.pk, search="cafe instantaneo", limit=10)
    assert [p.pk for p in items] == [cafe.pk]


@pytest.mark.django_db
def test_list_products_search_rapidfuzz_typo_still_matches():
    owner = _catalog_owner_user()
    milk = _catalog_product("Oat milk", owner=owner)
    _catalog_product("Rice", owner=owner)
    items, _ = list_products(user_id=owner.pk, search="ot mlk", limit=10)
    assert [p.pk for p in items] == [milk.pk]


@pytest.mark.django_db
def test_list_products_search_matches_keyword_in_long_standard_name():
    """Full-string WRatio underrates substring matches on long fields; gate uses per-field best."""
    owner = _catalog_owner_user()
    p = _catalog_product("SKU long label", owner=owner)
    Product.objects.filter(pk=p.pk).update(
        standard_name="Organic fair trade whole milk 1 L vitamin enriched",
        brand="Colún",
    )
    _catalog_product("Rice", owner=owner)
    items, _ = list_products(user_id=owner.pk, search="milk", limit=10)
    assert [i.pk for i in items] == [p.pk]


@pytest.mark.django_db
def test_list_products_search_paginates_with_cursor():
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
def test_list_products_rejects_mismatched_cursor():
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
def test_list_products_excludes_products_in_open_basket():
    u = _user()
    p_in = _catalog_product("In cart", owner=u)
    p_out = _catalog_product("Not in cart", owner=u)
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
    _catalog_product("A", owner=alice)
    _catalog_product("B", owner=alice)
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
@patch("groceries.services.gemini_service.fetch_merchant_product_info_by_identity")
def test_recheck_product_price_passes_preferred_merchants(mock_identity):
    mock_identity.return_value = None
    owner = _catalog_owner_user()
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
    owner = _catalog_owner_user()
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
    owner = _catalog_owner_user()
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


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.suggest_running_low_from_purchase_history",
)
def test_sync_running_low_skips_snoozed_product(mock_suggest):
    utc = ZoneInfo("UTC")
    user = _user(username="snooze_rl")
    milk = _catalog_product("Milk", owner=user)
    jam = _catalog_product("Jam", owner=user)
    Product.objects.filter(pk__in=[milk.pk, jam.pk]).update(purchase_count=2)
    b = Basket.objects.create(owner=user, purchased_at=timezone.now())
    b.products.add(milk, jam)
    Product.objects.filter(pk=milk.pk).update(running_low=True)
    future = datetime(2026, 6, 1, 12, 0, 0, tzinfo=utc)
    Product.objects.filter(pk=milk.pk).update(running_low_snoozed_until=future)
    with patch("groceries.services.timezone.now") as mock_now:
        mock_now.return_value = datetime(2026, 5, 1, 12, 0, 0, tzinfo=utc)
        mock_suggest.return_value = [
            RunningLowSuggestion(
                product_name="Milk",
                reason="x",
                urgency="medium",
                product_ids=(milk.pk,),
            ),
        ]
        sync_running_low_flags_for_user(user_id=user.pk)
    md = mock_suggest.call_args.kwargs["history_markdown"]
    assert f"[product_id={milk.pk}]" not in md
    assert "Jam" in md
    assert not Product.objects.get(pk=milk.pk).running_low


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.suggest_running_low_from_purchase_history",
    return_value=[],
)
def test_sync_running_low_renumbers_baskets_when_snoozed_lines_removed(mock_suggest):
    utc = ZoneInfo("UTC")
    user = _user(username="snooze_renum")
    milk = _catalog_product("Milk", owner=user)
    jam = _catalog_product("Jam", owner=user)
    Product.objects.filter(pk__in=[milk.pk, jam.pk]).update(purchase_count=2)
    future = datetime(2026, 6, 1, 12, 0, 0, tzinfo=utc)
    Product.objects.filter(pk=milk.pk).update(running_low_snoozed_until=future)
    with patch("groceries.services.timezone.now") as mock_now:
        mock_now.return_value = datetime(2026, 5, 1, 12, 0, 0, tzinfo=utc)
        b_old = Basket.objects.create(
            owner=user,
            purchased_at=datetime(2026, 5, 1, 10, 0, 0, tzinfo=utc),
        )
        b_old.products.add(milk)
        b_new = Basket.objects.create(
            owner=user,
            purchased_at=datetime(2026, 5, 1, 11, 0, 0, tzinfo=utc),
        )
        b_new.products.add(jam)
        sync_running_low_flags_for_user(user_id=user.pk)
    md = mock_suggest.call_args.kwargs["history_markdown"]
    assert "Basket 1" in md
    assert "Basket 2" not in md
    assert "Jam" in md
    assert f"[product_id={milk.pk}]" not in md


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.suggest_running_low_from_purchase_history",
)
def test_sync_running_low_clears_running_low_even_when_snoozed(mock_suggest):
    utc = ZoneInfo("UTC")
    mock_suggest.return_value = []
    user = _user(username="snooze_clear")
    milk = _catalog_product("Milk", owner=user)
    Product.objects.filter(pk=milk.pk).update(purchase_count=2)
    b = Basket.objects.create(owner=user, purchased_at=timezone.now())
    b.products.add(milk)
    future = datetime(2026, 6, 1, 12, 0, 0, tzinfo=utc)
    Product.objects.filter(pk=milk.pk).update(
        running_low=True,
        running_low_snoozed_until=future,
    )
    with patch("groceries.services.timezone.now") as mock_now:
        mock_now.return_value = datetime(2026, 5, 1, 12, 0, 0, tzinfo=utc)
        sync_running_low_flags_for_user(user_id=user.pk)
    milk.refresh_from_db()
    assert not milk.running_low
    mock_suggest.assert_not_called()


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.suggest_running_low_from_purchase_history",
)
def test_sync_running_low_flags_after_snooze_expires(mock_suggest):
    utc = ZoneInfo("UTC")
    santiago = ZoneInfo("America/Santiago")
    user = _user(username="snooze_exp")
    milk = _catalog_product("Milk", owner=user)
    Product.objects.filter(pk=milk.pk).update(purchase_count=2)
    b = Basket.objects.create(
        owner=user,
        purchased_at=datetime(2026, 4, 30, 10, 0, 0, tzinfo=santiago),
    )
    b.products.add(milk)
    Product.objects.filter(pk=milk.pk).update(
        running_low_snoozed_until=datetime(2026, 5, 1, 12, 0, 0, tzinfo=utc),
    )
    with patch("groceries.services.timezone.now") as mock_now:
        mock_now.return_value = datetime(2026, 5, 3, 12, 0, 0, tzinfo=santiago)
        mock_suggest.return_value = [
            RunningLowSuggestion(
                product_name="Milk",
                reason="x",
                urgency="medium",
                product_ids=(milk.pk,),
            ),
        ]
        sync_running_low_flags_for_user(user_id=user.pk)
    assert Product.objects.get(pk=milk.pk).running_low


@pytest.mark.django_db
def test_add_product_to_basket_creates_basket_when_none_open():
    user = _user()
    pid = _catalog_product("Milk").pk
    basket = add_product_to_basket(product_id=pid, user_id=user.pk)
    assert basket.pk is not None
    assert basket.purchased_at is None
    assert list(basket.products.values_list("pk", flat=True)) == [pid]


@pytest.mark.django_db
def test_add_product_to_basket_reuses_latest_open_basket():
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
def test_add_product_to_basket_line_defaults_purchase_true():
    user = _user()
    pid = _catalog_product("Milk").pk
    basket = add_product_to_basket(product_id=pid, user_id=user.pk)
    row = BasketProduct.objects.get(basket_id=basket.pk, product_id=pid)
    assert row.purchase is True


@pytest.mark.django_db
def test_add_product_to_basket_skips_purchased_baskets():
    user = _user()
    p = _catalog_product("X").pk
    open_b = Basket.objects.create(owner=user)
    Basket.objects.create(owner=user, purchased_at=timezone.now())
    out = add_product_to_basket(product_id=p, user_id=user.pk)
    assert out.pk == open_b.pk


@pytest.mark.django_db
def test_add_product_to_basket_raises_when_product_missing():
    user = _user()
    with pytest.raises(Product.DoesNotExist):
        add_product_to_basket(product_id=99999, user_id=user.pk)


@pytest.mark.django_db
def test_delete_product_from_basket_removes_line():
    user = _user()
    pid = _catalog_product("Milk").pk
    add_product_to_basket(product_id=pid, user_id=user.pk)
    delete_product_from_basket(product_id=pid, user_id=user.pk)
    b = Basket.objects.get(owner=user, purchased_at__isnull=True)
    assert b.products.count() == 0


@pytest.mark.django_db
def test_delete_product_from_basket_targets_latest_open_basket():
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
def test_delete_product_from_basket_noop_when_product_not_in_basket():
    user = _user()
    pid = _catalog_product("Y").pk
    Basket.objects.create(owner=user)
    delete_product_from_basket(product_id=pid, user_id=user.pk)
    assert (
        Basket.objects.get(owner=user, purchased_at__isnull=True).products.count() == 0
    )


@pytest.mark.django_db
def test_delete_product_from_basket_raises_when_no_open_basket():
    user = _user()
    pid = _catalog_product("Z").pk
    Basket.objects.create(owner=user, purchased_at=timezone.now())
    with pytest.raises(NoOpenBasketError):
        delete_product_from_basket(product_id=pid, user_id=user.pk)


@pytest.mark.django_db
def test_delete_product_from_basket_raises_when_product_missing():
    user = _user()
    Basket.objects.create(owner=user)
    with pytest.raises(Product.DoesNotExist):
        delete_product_from_basket(product_id=99999, user_id=user.pk)


@pytest.mark.django_db
def test_delete_product_from_basket_purchased_basket_by_id_removes_line():
    user = _user()
    pid = _catalog_product("Past").pk
    past = Basket.objects.create(owner=user, purchased_at=timezone.now())
    past.products.add(pid)
    delete_product_from_basket(product_id=pid, user_id=user.pk, basket_id=past.pk)
    past.refresh_from_db()
    assert past.products.count() == 0


@pytest.mark.django_db
def test_delete_product_from_basket_purchased_noop_when_product_absent():
    user = _user()
    pid = _catalog_product("Solo").pk
    past = Basket.objects.create(owner=user, purchased_at=timezone.now())
    delete_product_from_basket(product_id=pid, user_id=user.pk, basket_id=past.pk)
    assert past.products.count() == 0


@pytest.mark.django_db
def test_delete_product_from_basket_by_id_raises_when_open_basket():
    user = _user()
    pid = _catalog_product("Open").pk
    open_b = Basket.objects.create(owner=user)
    open_b.products.add(pid)
    with pytest.raises(ValueError, match="past \\(purchased\\)"):
        delete_product_from_basket(
            product_id=pid,
            user_id=user.pk,
            basket_id=open_b.pk,
        )


@pytest.mark.django_db
def test_delete_product_from_basket_by_id_other_user_basket():
    user = _user()
    other = _user(username="u_other")
    pid = _catalog_product("Mine").pk
    past = Basket.objects.create(owner=other, purchased_at=timezone.now())
    past.products.add(pid)
    with pytest.raises(Basket.DoesNotExist):
        delete_product_from_basket(
            product_id=pid,
            user_id=user.pk,
            basket_id=past.pk,
        )


@pytest.mark.django_db
def test_get_current_basket_with_products_none_when_empty():
    user = _user()
    assert get_current_basket_with_products(user_id=user.pk) is None


@pytest.mark.django_db
def test_get_current_basket_with_products_returns_newest_and_ordered_products():
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
def test_get_current_basket_with_products_excludes_purchased_only():
    user = _user()
    pid = _catalog_product("Z").pk
    b = Basket.objects.create(owner=user, purchased_at=timezone.now())
    b.products.add(pid)
    assert get_current_basket_with_products(user_id=user.pk) is None


@pytest.mark.django_db
def test_get_current_basket_with_products_prefers_open_when_newer_is_purchased():
    user = _user()
    pid_open = _catalog_product("Open").pk
    pid_bought = _catalog_product("Bought").pk
    older_open = Basket.objects.create(owner=user)
    older_open.products.add(pid_open)
    newer_purchased = Basket.objects.create(owner=user, purchased_at=timezone.now())
    newer_purchased.products.add(pid_bought)
    out = get_current_basket_with_products(user_id=user.pk)
    assert out is not None
    assert out.pk == older_open.pk
    assert list(out.products.values_list("pk", flat=True)) == [pid_open]


@pytest.mark.django_db
def test_purchase_latest_open_basket_sets_purchased_at():
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
def test_purchase_latest_open_basket_increments_each_product_once():
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
def test_purchase_latest_open_basket_clears_running_low():
    user = _user()
    b = Basket.objects.create(owner=user)
    p = Product.objects.create(name="Milk", user=user, running_low=True)
    b.products.add(p)
    purchase_latest_open_basket(user_id=user.pk)
    p.refresh_from_db()
    assert not p.running_low
    assert p.running_low_snoozed_until is None


@pytest.mark.django_db
def test_second_purchase_increments_again():
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
def test_recalculate_purchase_counts_from_baskets_subset():
    user = _user()
    p = Product.objects.create(name="Milk", user=user, purchase_count=99)
    b = Basket.objects.create(owner=user, purchased_at=timezone.now())
    b.products.add(p)
    Product.objects.filter(pk=p.pk).update(purchase_count=99)
    recalculate_product_purchase_counts_from_baskets(product_ids=[p.pk])
    p.refresh_from_db()
    assert p.purchase_count == 1


@pytest.mark.django_db
def test_recalculate_purchase_counts_from_baskets_respects_purchase_false():
    user = _user()
    p = Product.objects.create(name="Defer", user=user, purchase_count=5)
    b = Basket.objects.create(owner=user, purchased_at=timezone.now())
    b.products.add(p, through_defaults={"purchase": False})
    recalculate_product_purchase_counts_from_baskets(product_ids=[p.pk])
    p.refresh_from_db()
    assert p.purchase_count == 0


@pytest.mark.django_db
def test_recalculate_purchase_counts_from_baskets_global():
    user = _user()
    a = Product.objects.create(name="A", user=user, purchase_count=0)
    b = Product.objects.create(name="B", user=user, purchase_count=9)
    basket = Basket.objects.create(owner=user, purchased_at=timezone.now())
    basket.products.add(a)
    basket2 = Basket.objects.create(owner=user, purchased_at=timezone.now())
    basket2.products.add(a)
    n = recalculate_product_purchase_counts_from_baskets()
    assert n == Product.all_objects.count()
    a.refresh_from_db()
    b.refresh_from_db()
    assert a.purchase_count == 2
    assert b.purchase_count == 0


@pytest.mark.django_db
def test_purchase_moves_deferred_lines_to_new_open_basket():
    user = _user()
    b = Basket.objects.create(owner=user)
    buy = Product.objects.create(name="Buy", user=user)
    defer = Product.objects.create(name="Defer", user=user)
    Product.objects.filter(pk__in=[buy.pk, defer.pk]).update(running_low=True)
    b.products.add(buy, defer)
    set_product_purchase_in_open_basket(
        product_id=defer.pk,
        user_id=user.pk,
        purchase=False,
    )
    purchased = purchase_latest_open_basket(user_id=user.pk)
    buy.refresh_from_db()
    defer.refresh_from_db()
    assert buy.purchase_count == 1
    assert defer.purchase_count == 0
    assert not buy.running_low
    assert defer.running_low
    purchased.refresh_from_db()
    assert purchased.purchased_at is not None
    assert list(purchased.products.values_list("pk", flat=True)) == [buy.pk]
    nxt = get_current_basket(user_id=user.pk)
    assert nxt is not None
    assert nxt.pk != purchased.pk
    assert list(nxt.products.values_list("pk", flat=True)) == [defer.pk]
    lines = basket_product_lines(basket_id=nxt.pk)
    assert lines == [(defer, False)]


@pytest.mark.django_db
def test_set_product_purchase_in_open_basket_raises_when_line_missing():
    user = _user()
    Basket.objects.create(owner=user)
    orphan = Product.objects.create(name="X", user=user)
    with pytest.raises(ValueError, match="not in the current basket"):
        set_product_purchase_in_open_basket(
            product_id=orphan.pk,
            user_id=user.pk,
            purchase=False,
        )


@pytest.mark.django_db
def test_purchase_latest_open_basket_skips_already_purchased():
    user = _user()
    open_b = Basket.objects.create(owner=user)
    Basket.objects.create(owner=user, purchased_at=timezone.now())
    out = purchase_latest_open_basket(user_id=user.pk)
    assert out.pk == open_b.pk
    open_b.refresh_from_db()
    assert open_b.purchased_at is not None


@pytest.mark.django_db
def test_purchase_latest_open_basket_raises_when_none_open():
    user = _user()
    Basket.objects.create(owner=user, purchased_at=timezone.now())
    with pytest.raises(NoOpenBasketError):
        purchase_latest_open_basket(user_id=user.pk)


@pytest.mark.django_db
def test_purchase_single_product_creates_purchased_basket_and_increments():
    user = _user()
    p = Product.objects.create(name="Solo", user=user)
    out = purchase_single_product(product_id=p.pk, user_id=user.pk)
    out.refresh_from_db()
    p.refresh_from_db()
    assert out.purchased_at is not None
    assert list(out.products.values_list("pk", flat=True)) == [p.pk]
    assert p.purchase_count == 1


@pytest.mark.django_db
def test_purchase_single_product_clears_running_low():
    user = _user()
    p = Product.objects.create(name="Solo", user=user, running_low=True)
    purchase_single_product(product_id=p.pk, user_id=user.pk)
    assert not Product.objects.get(pk=p.pk).running_low


@pytest.mark.django_db
def test_purchase_single_product_does_not_touch_existing_open_basket():
    user = _user()
    existing = Basket.objects.create(owner=user)
    other = Product.objects.create(name="In cart", user=user)
    existing.products.add(other)
    solo = Product.objects.create(name="Instant", user=user)
    purchase_single_product(product_id=solo.pk, user_id=user.pk)
    existing.refresh_from_db()
    assert existing.purchased_at is None
    assert list(existing.products.values_list("pk", flat=True)) == [other.pk]
    cur = get_current_basket(user_id=user.pk)
    assert cur is not None
    assert cur.pk == existing.pk


@pytest.mark.django_db
def test_purchase_single_product_removes_product_from_current_basket():
    user = _user()
    open_b = Basket.objects.create(owner=user)
    solo = Product.objects.create(name="Instant", user=user)
    open_b.products.add(solo)
    out = purchase_single_product(product_id=solo.pk, user_id=user.pk)
    open_b.refresh_from_db()
    assert list(open_b.products.values_list("pk", flat=True)) == []
    assert list(out.products.values_list("pk", flat=True)) == [solo.pk]
    assert out.purchased_at is not None


@pytest.mark.django_db
def test_basket_operations_isolated_per_user():
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
def test_list_purchased_baskets_empty():
    user = _user()
    assert list_purchased_baskets(user_id=user.pk) == []


@pytest.mark.django_db
def test_list_purchased_baskets_excludes_open():
    user = _user()
    Basket.objects.create(owner=user)
    b2 = Basket.objects.create(owner=user, purchased_at=timezone.now())
    rows = list_purchased_baskets(user_id=user.pk)
    assert len(rows) == 1
    assert rows[0].pk == b2.pk


@pytest.mark.django_db
def test_list_purchased_baskets_prefetch_includes_soft_deleted_products():
    user = _user()
    p = Product.objects.create(name="Milk", user=user)
    b = Basket.objects.create(owner=user, purchased_at=timezone.now())
    b.products.add(p)
    delete_product(product_id=p.pk, user_id=user.pk)
    rows = list_purchased_baskets(user_id=user.pk)
    assert len(rows) == 1
    prefetched = list(rows[0]._prefetched_objects_cache["products"])
    assert len(prefetched) == 1
    assert prefetched[0].pk == p.pk
    assert prefetched[0].deleted_at is not None


@pytest.mark.django_db
def test_list_purchased_baskets_caps_at_limit_newest_by_purchased_at():
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
def test_list_purchased_baskets_isolated_per_user():
    alice = _user(username="alice2")
    bob = _user(username="bob2")
    Basket.objects.create(owner=alice, purchased_at=timezone.now())
    assert list_purchased_baskets(user_id=bob.pk) == []


@pytest.mark.django_db
def test_list_purchased_baskets_for_running_low_empty():
    user = _user(username="rl_window_empty")
    assert list_purchased_baskets_for_running_low(user_id=user.pk) == []


@pytest.mark.django_db
@patch("groceries.services.timezone.now")
def test_list_purchased_baskets_for_running_low_two_month_window(mock_now):
    """Only baskets with purchased_at >= now - 2 months (inclusive boundary)."""
    utc = ZoneInfo("UTC")
    mock_now.return_value = datetime(2026, 3, 15, 12, 0, 0, tzinfo=utc)
    # Two months before mock_now is 2026-01-15 12:00 UTC
    user = _user(username="rl_window")
    too_old = Basket.objects.create(
        owner=user,
        purchased_at=datetime(2026, 1, 14, 23, 59, 59, tzinfo=utc),
    )
    on_edge = Basket.objects.create(
        owner=user,
        purchased_at=datetime(2026, 1, 15, 12, 0, 0, tzinfo=utc),
    )
    recent = Basket.objects.create(
        owner=user,
        purchased_at=datetime(2026, 3, 1, 8, 0, 0, tzinfo=utc),
    )
    rows = list_purchased_baskets_for_running_low(user_id=user.pk)
    assert {b.pk for b in rows} == {on_edge.pk, recent.pk}
    assert too_old.pk not in {b.pk for b in rows}
    assert [b.pk for b in rows] == [recent.pk, on_edge.pk]


@pytest.mark.django_db
def test_list_purchased_baskets_for_running_low_prefetch_excludes_soft_deleted_products():
    user = _user()
    p = Product.objects.create(name="Milk", user=user, purchase_count=2)
    b = Basket.objects.create(owner=user, purchased_at=timezone.now())
    b.products.add(p)
    delete_product(product_id=p.pk, user_id=user.pk)
    rows = list_purchased_baskets_for_running_low(user_id=user.pk)
    assert len(rows) == 1
    prefetched = list(rows[0]._prefetched_objects_cache["products"])
    assert prefetched == []


@pytest.mark.django_db
def test_list_purchased_baskets_for_running_low_omits_single_purchase_products():
    """Running-low history for Gemini excludes lines where purchase_count is 1."""
    user = _user(username="rl_once")
    once = Product.objects.create(name="Try once", user=user, purchase_count=1)
    repeat = Product.objects.create(name="Staple", user=user, purchase_count=2)
    b = Basket.objects.create(owner=user, purchased_at=timezone.now())
    b.products.add(once, repeat)
    rows = list_purchased_baskets_for_running_low(user_id=user.pk)
    assert len(rows) == 1
    names = {p.name for p in rows[0]._prefetched_objects_cache["products"]}
    assert names == {"Staple"}


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.suggest_running_low_from_purchase_history",
)
def test_sync_running_low_skips_gemini_when_only_single_purchase_products(mock_suggest):
    """No Gemini call when every line in window is a one-off buy (purchase_count < 2)."""
    mock_suggest.return_value = []
    user = _user(username="rl_only_once")
    milk = _catalog_product("Milk", owner=user)
    Product.objects.filter(pk=milk.pk).update(purchase_count=1)
    b = Basket.objects.create(owner=user, purchased_at=timezone.now())
    b.products.add(milk)
    sync_running_low_flags_for_user(user_id=user.pk)
    mock_suggest.assert_not_called()


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.suggest_running_low_from_purchase_history",
    return_value=[],
)
def test_sync_running_low_history_omits_soft_deleted_products(mock_suggest):
    user = _user(username="rl_soft")
    gone = Product.objects.create(name="Gone", user=user, purchase_count=2)
    keep = Product.objects.create(name="Staple", user=user, purchase_count=2)
    b = Basket.objects.create(owner=user, purchased_at=timezone.now())
    b.products.add(gone, keep)
    delete_product(product_id=gone.pk, user_id=user.pk)
    sync_running_low_flags_for_user(user_id=user.pk)
    md = mock_suggest.call_args.kwargs["history_markdown"]
    assert "Gone" not in md
    assert "Staple" in md


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.suggest_running_low_from_purchase_history",
)
def test_sync_running_low_uses_two_month_purchase_window_only(mock_suggest):
    utc = ZoneInfo("UTC")
    mock_suggest.return_value = []
    user = _user(username="rl_sync_window")
    old_milk = _catalog_product("Old milk", owner=user)
    Product.objects.filter(pk=old_milk.pk).update(purchase_count=2)
    new_jam = _catalog_product("Jam", owner=user)
    Product.objects.filter(pk=new_jam.pk).update(purchase_count=2)
    with patch("groceries.services.timezone.now") as mock_now:
        mock_now.return_value = datetime(2026, 3, 15, 12, 0, 0, tzinfo=utc)
        b_old = Basket.objects.create(
            owner=user,
            purchased_at=datetime(2025, 12, 1, 10, 0, 0, tzinfo=utc),
        )
        b_old.products.add(old_milk)
        b_new = Basket.objects.create(
            owner=user,
            purchased_at=datetime(2026, 3, 10, 10, 0, 0, tzinfo=utc),
        )
        b_new.products.add(new_jam)
        sync_running_low_flags_for_user(user_id=user.pk)
    md = mock_suggest.call_args.kwargs["history_markdown"]
    assert "Jam" in md
    assert "Old milk" not in md


@pytest.mark.django_db
def test_sync_running_low_clears_when_no_purchased_baskets():
    user = _user(username="noruns")
    p = _catalog_product("X", owner=user)
    Product.objects.filter(pk=p.pk).update(running_low=True)
    sync_running_low_flags_for_user(user_id=user.pk)
    assert not Product.objects.get(pk=p.pk).running_low


@pytest.mark.django_db
@override_settings(TIME_ZONE="America/Santiago")
@patch(
    "groceries.services.gemini_service.suggest_running_low_from_purchase_history",
)
def test_sync_running_low_calls_gemini_and_sets_flags(mock_suggest):
    chile = ZoneInfo("America/Santiago")
    mock_suggest.return_value = [
        RunningLowSuggestion(
            product_name="Leche",
            reason="Última compra hace tiempo.",
            urgency="medium",
            product_ids=(999,),
        ),
    ]
    user = _user(username="runlow")
    milk = _catalog_product("Leche entera", owner=user)
    Product.objects.filter(pk=milk.pk).update(purchase_count=2)
    b = Basket.objects.create(
        owner=user,
        purchased_at=datetime(2026, 4, 28, 10, 0, 0, tzinfo=chile),
    )
    b.products.add(milk)

    with patch("groceries.services.timezone.now") as mock_now:
        mock_now.return_value = datetime(2026, 5, 3, 12, 0, 0, tzinfo=chile)
        sync_running_low_flags_for_user(user_id=user.pk)

    mock_suggest.assert_called_once()
    call_kw = mock_suggest.call_args.kwargs
    assert "history_markdown" in call_kw
    assert "Leche entera" in call_kw["history_markdown"]
    assert f"[product_id={milk.pk}]" in call_kw["history_markdown"]
    assert "Basket 1" in call_kw["history_markdown"]
    assert not Product.objects.get(pk=milk.pk).running_low

    mock_suggest.return_value = [
        RunningLowSuggestion(
            product_name="Leche",
            reason="x.",
            urgency="medium",
            product_ids=(milk.pk,),
        ),
    ]
    with patch("groceries.services.timezone.now") as mock_now:
        mock_now.return_value = datetime(2026, 5, 3, 12, 0, 0, tzinfo=chile)
        sync_running_low_flags_for_user(user_id=user.pk)
    assert Product.objects.get(pk=milk.pk).running_low


@pytest.mark.django_db
@override_settings(TIME_ZONE="America/Santiago")
@patch(
    "groceries.services.gemini_service.suggest_running_low_from_purchase_history",
)
def test_sync_running_low_skips_flag_when_purchased_today_or_yesterday(mock_suggest):
    chile = ZoneInfo("America/Santiago")
    user = _user(username="recent_buy")
    milk = _catalog_product("Milk", owner=user)
    Product.objects.filter(pk=milk.pk).update(purchase_count=2)
    b = Basket.objects.create(
        owner=user,
        purchased_at=datetime(2026, 5, 3, 9, 0, 0, tzinfo=chile),
    )
    b.products.add(milk)
    mock_suggest.return_value = [
        RunningLowSuggestion(
            product_name="Milk",
            reason="stock low",
            urgency="high",
            product_ids=(milk.pk,),
        ),
    ]
    with patch("groceries.services.timezone.now") as mock_now:
        mock_now.return_value = datetime(2026, 5, 3, 18, 0, 0, tzinfo=chile)
        sync_running_low_flags_for_user(user_id=user.pk)
    assert not Product.objects.get(pk=milk.pk).running_low


@pytest.mark.django_db
@override_settings(TIME_ZONE="America/Santiago")
@patch("groceries.services.send_email_via_gmail")
@patch(
    "groceries.services.gemini_service.suggest_running_low_from_purchase_history",
)
def test_sync_running_low_sends_digest_email_still_and_new(mock_suggest, mock_mail):
    chile = ZoneInfo("America/Santiago")
    user = _user(username="digest", email="shopper@example.com")
    milk = _catalog_product("Leche entera", owner=user)
    bread = _catalog_product("Pan integral", owner=user)
    Product.objects.filter(pk__in=[milk.pk, bread.pk]).update(purchase_count=2)
    Product.objects.filter(pk=milk.pk).update(running_low=True)
    b = Basket.objects.create(
        owner=user,
        purchased_at=datetime(2026, 4, 25, 10, 0, 0, tzinfo=chile),
    )
    b.products.add(milk, bread)
    mock_suggest.return_value = [
        RunningLowSuggestion(
            product_name="Leche",
            reason="Última compra hace tiempo.",
            urgency="medium",
            product_ids=(milk.pk,),
        ),
        RunningLowSuggestion(
            product_name="Pan",
            reason="Compras frecuentes.",
            urgency="high",
            product_ids=(bread.pk,),
        ),
    ]

    with patch("groceries.services.timezone.now") as mock_now:
        mock_now.return_value = datetime(2026, 5, 3, 12, 0, 0, tzinfo=chile)
        sync_running_low_flags_for_user(user_id=user.pk)

    mock_mail.assert_called_once()
    kw = mock_mail.call_args.kwargs
    assert kw["to_addrs"] == ["shopper@example.com"]
    assert kw["subject"] == "Groceries: products running low"
    body = kw["body"]
    assert "Still running low" in body
    assert "Newly flagged" in body
    assert f"[product_id={milk.pk}]" in body
    assert f"[product_id={bread.pk}]" in body
    assert "Última compra hace tiempo." in body
    assert "Compras frecuentes." in body


@pytest.mark.django_db
@override_settings(TIME_ZONE="America/Santiago")
@patch("groceries.services.send_email_via_gmail")
@patch(
    "groceries.services.gemini_service.suggest_running_low_from_purchase_history",
)
def test_sync_running_low_skips_email_when_user_has_no_email(mock_suggest, mock_mail):
    chile = ZoneInfo("America/Santiago")
    user = _user(username="noaddr", email="")
    milk = _catalog_product("Leche", owner=user)
    Product.objects.filter(pk=milk.pk).update(purchase_count=2)
    b = Basket.objects.create(
        owner=user,
        purchased_at=datetime(2026, 4, 20, 10, 0, 0, tzinfo=chile),
    )
    b.products.add(milk)
    mock_suggest.return_value = [
        RunningLowSuggestion(
            product_name="Leche",
            reason="x.",
            urgency="medium",
            product_ids=(milk.pk,),
        ),
    ]

    with patch("groceries.services.timezone.now") as mock_now:
        mock_now.return_value = datetime(2026, 5, 3, 12, 0, 0, tzinfo=chile)
        sync_running_low_flags_for_user(user_id=user.pk)

    mock_mail.assert_not_called()


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.suggest_running_low_from_purchase_history",
    side_effect=RuntimeError("no key"),
)
def test_sync_running_low_clears_when_gemini_unconfigured(_mock_suggest):
    user = _user(username="nokey")
    milk = _catalog_product("Leche", owner=user)
    Product.objects.filter(pk=milk.pk).update(purchase_count=2)
    Product.objects.filter(pk=milk.pk).update(running_low=True)
    b = Basket.objects.create(owner=user, purchased_at=timezone.now())
    b.products.add(milk)
    sync_running_low_flags_for_user(user_id=user.pk)
    assert not Product.objects.get(pk=milk.pk).running_low


@pytest.mark.django_db
def test_running_low_sync_user_ids_distinct_owners():
    a = _user(username="rl_a")
    b = _user(username="rl_b")
    _catalog_product("p", owner=a)
    _catalog_product("p2", owner=a)
    _catalog_product("q", owner=b)
    uids = running_low_sync_user_ids()
    assert sorted(uids) == sorted([a.pk, b.pk])


@pytest.mark.django_db
@patch("groceries.services.async_task")
@patch("groceries.services.gemini_service.suggest_product_emoji", return_value="")
@patch("groceries.services.gemini_service.fetch_recipe_full_chile")
def test_create_recipe_from_title_and_notes_persists_gemini_output(
    mock_fetch,
    _mock_suggest,
    mock_async,
):
    u = _user(username="chef1")
    mock_fetch.return_value = RecipeFullFromGemini(
        ingredients=(
            RecipeIngredientLine(name="Papa", amount="500 g"),
            RecipeIngredientLine(name="Cebolla", amount="1 unidad"),
        ),
        steps=("Pelar papas.", "Hervir 15 min."),
        emoji="🥘",
    )
    r = create_recipe_from_title_and_notes(
        title="  Charquicán  ",
        notes="  sin carne  ",
        user_id=u.pk,
    )
    mock_async.assert_called_once_with(
        "groceries.scheduled_tasks.run_recipe_gemini_job",
        r.pk,
        task_name=f"groceries_recipe_gemini:{r.pk}",
    )
    mock_fetch.assert_not_called()
    row = Recipe.objects.get(pk=r.pk)
    assert row.generation_status == RecipeGenerationStatus.PENDING
    run_recipe_gemini_job(recipe_id=r.pk)
    mock_fetch.assert_called_once_with(title="Charquicán", notes="sin carne")
    row = Recipe.objects.get(pk=r.pk)
    assert row.user_id == u.pk
    assert row.title == "Charquicán"
    assert row.notes == "sin carne"
    assert row.generation_status == RecipeGenerationStatus.COMPLETED
    assert row.emoji == "🥘"
    ings = list(row.ingredients.order_by("order", "id"))
    assert len(ings) == 2
    assert ings[0].name == "Papa" and ings[0].amount == "500 g"
    sts = list(row.steps.order_by("order", "id"))
    assert len(sts) == 2
    assert sts[0].text == "Pelar papas."


@pytest.mark.django_db
@patch("groceries.services.async_task")
@patch("groceries.services.gemini_service.fetch_recipe_full_chile", return_value=None)
def test_run_recipe_gemini_job_marks_failed_when_gemini_empty(_mock_fetch, _mock_async):
    u = _user()
    r = create_recipe_from_title_and_notes(title="X", notes="", user_id=u.pk)
    run_recipe_gemini_job(recipe_id=r.pk)
    row = Recipe.objects.get(pk=r.pk)
    assert row.generation_status == RecipeGenerationStatus.FAILED
    assert row.generation_error_message
    assert row.ingredients.count() == 0


@pytest.mark.django_db
def test_create_recipe_from_title_and_notes_empty_title_raises():
    u = _user()
    with pytest.raises(ValueError, match="title"):
        create_recipe_from_title_and_notes(title="   ", notes="", user_id=u.pk)


@pytest.mark.django_db
@patch("groceries.services.async_task")
def test_create_recipe_placeholder_notes_stored_empty(_mock_async):
    u = _user()
    r = create_recipe_from_title_and_notes(
        title="Pollo",
        notes="  Sin notas  ",
        user_id=u.pk,
    )
    assert Recipe.objects.get(pk=r.pk).notes == ""


@pytest.mark.django_db
@patch("groceries.services.async_task")
def test_create_recipe_from_title_sets_default_emoji_before_generation(_mock_async):
    u = _user()
    r = create_recipe_from_title_and_notes(title="Tortilla", notes="", user_id=u.pk)
    row = Recipe.objects.get(pk=r.pk)
    assert row.emoji == SEARCH_DEFAULT_EMOJI
    assert row.generation_status == RecipeGenerationStatus.PENDING


@pytest.mark.django_db
@patch("groceries.services.async_task")
@patch("groceries.services.gemini_service.suggest_product_emoji", return_value="🧄")
@patch("groceries.services.gemini_service.fetch_recipe_full_chile")
def test_run_recipe_gemini_job_uses_suggest_emoji_when_json_omits_emoji(
    mock_fetch,
    mock_suggest,
    _mock_async,
):
    u = _user(username="chef_emoji_fallback")
    mock_fetch.return_value = RecipeFullFromGemini(
        ingredients=(RecipeIngredientLine(name="Ajo", amount="1"),),
        steps=("Sofreír.",),
    )
    r = create_recipe_from_title_and_notes(title="Salsa verde", notes="", user_id=u.pk)
    run_recipe_gemini_job(recipe_id=r.pk)
    row = Recipe.objects.get(pk=r.pk)
    assert row.emoji == "🧄"
    mock_suggest.assert_called_once_with(name="Salsa verde")


@pytest.mark.django_db
@patch("groceries.services.async_task")
@patch("groceries.services.gemini_service.suggest_product_emoji", return_value="")
@patch("groceries.services.gemini_service.fetch_recipe_full_chile")
def test_get_recipe_returns_row_for_owner(mock_fetch, _mock_suggest, _mock_async):
    u = _user(username="chef2")
    u2 = _user(username="other")
    mock_fetch.return_value = RecipeFullFromGemini(
        ingredients=(RecipeIngredientLine(name="Ajo", amount="2 dientes"),),
        steps=("Picar.",),
    )
    r = create_recipe_from_title_and_notes(title="Salsa", notes="", user_id=u.pk)
    run_recipe_gemini_job(recipe_id=r.pk)
    out = get_recipe(recipe_id=r.pk, user_id=u.pk)
    assert out.pk == r.pk
    assert list(out.ingredients.values_list("name", flat=True)) == ["Ajo"]
    with pytest.raises(Recipe.DoesNotExist):
        get_recipe(recipe_id=r.pk, user_id=u2.pk)


@pytest.mark.django_db
def test_recipe_ingredient_in_catalog_flags_icontains_standard_name():
    u = _user(username="chef_cat")
    Product.objects.create(
        user=u,
        name="Leche Colún",
        standard_name="Leche entera 1 L",
        brand="Colún",
        price=Decimal("1000"),
        format="1 L",
    )
    flags = recipe_ingredient_in_catalog_flags(
        user_id=u.pk,
        ingredient_names=["Leche", "Huevos", "  leche  "],
    )
    assert flags["Leche"] is True
    assert flags["Huevos"] is False
    assert flags["leche"] is True


@pytest.mark.django_db
def test_list_recipe_messages_ordered_oldest_first():
    u = _user(username="msg_list_u")
    r = Recipe.objects.create(user=u, title="Chatty", notes="")
    RecipeIngredient.objects.create(recipe=r, order=0, name="A", amount="")
    RecipeStep.objects.create(recipe=r, order=0, text="S")
    base = timezone.now()
    m1 = RecipeMessage.objects.create(
        recipe=r,
        user_message="first",
        assistant_answer="a1",
        recipe_updated=False,
    )
    RecipeMessage.objects.filter(pk=m1.pk).update(created_at=base)
    m2 = RecipeMessage.objects.create(
        recipe=r,
        user_message="second",
        assistant_answer="a2",
        recipe_updated=True,
    )
    RecipeMessage.objects.filter(pk=m2.pk).update(created_at=base + timedelta(seconds=1))

    rows = list_recipe_messages(recipe_id=r.pk, user_id=u.pk)
    assert [m.pk for m in rows] == [m1.pk, m2.pk]
    assert rows[0].user_message == "first"
    assert rows[1].recipe_updated is True


@pytest.mark.django_db
def test_list_recipe_messages_wrong_user_raises():
    u = _user(username="msg_owner")
    other = _user(username="msg_other")
    r = Recipe.objects.create(user=u, title="Mine", notes="")
    RecipeIngredient.objects.create(recipe=r, order=0, name="A", amount="")
    RecipeStep.objects.create(recipe=r, order=0, text="S")
    RecipeMessage.objects.create(
        recipe=r,
        user_message="x",
        assistant_answer="y",
        recipe_updated=False,
    )
    with pytest.raises(Recipe.DoesNotExist):
        list_recipe_messages(recipe_id=r.pk, user_id=other.pk)


@pytest.mark.django_db
def test_delete_recipe_removes_row_and_children():
    u = _user(username="chef_del")
    r = Recipe.objects.create(user=u, title="Gone", notes="")
    RecipeIngredient.objects.create(recipe=r, order=0, name="X", amount="")
    RecipeStep.objects.create(recipe=r, order=0, text="Y")
    rid = r.pk
    RecipeMessage.objects.create(
        recipe=r,
        user_message="hi",
        assistant_answer="bye",
        recipe_updated=False,
    )
    delete_recipe(recipe_id=rid, user_id=u.pk)
    assert Recipe.objects.filter(pk=rid).count() == 0
    assert RecipeIngredient.objects.filter(recipe_id=rid).count() == 0
    assert RecipeStep.objects.filter(recipe_id=rid).count() == 0
    assert RecipeMessage.objects.filter(recipe_id=rid).count() == 0


@pytest.mark.django_db
@patch("groceries.services.gemini_service.fetch_recipe_chat_chile")
def test_recipe_chat_about_recipe_answer_only_no_db_change(mock_fetch):
    from groceries.gemini_service import RecipeChatFromGemini

    u = _user(username="chat_u1")
    r = Recipe.objects.create(user=u, title="Sopa", notes="")
    RecipeIngredient.objects.create(recipe=r, order=0, name="Agua", amount="1 L")
    RecipeStep.objects.create(recipe=r, order=0, text="Hervir.")
    raw = '{"answer": "Prueba de sal al final.", "update_recipe": false}'
    mock_fetch.return_value = RecipeChatFromGemini(
        answer="Prueba de sal al final.",
        update_recipe=False,
        updated=None,
        gemini_response_raw=raw,
    )

    out = recipe_chat_about_recipe(
        recipe_id=r.pk,
        user_id=u.pk,
        message="  ¿Cuándo sal?  ",
    )
    assert out.answer == "Prueba de sal al final."
    assert out.recipe_updated is False
    row = get_recipe(recipe_id=r.pk, user_id=u.pk)
    assert row.title == "Sopa"
    assert list(
        row.ingredients.order_by("order").values_list("name", flat=True),
    ) == ["Agua"]
    mock_fetch.assert_called_once()
    stored = RecipeMessage.objects.get(recipe_id=r.pk)
    assert stored.user_message == "¿Cuándo sal?"
    assert stored.assistant_answer == "Prueba de sal al final."
    assert stored.gemini_response_raw == raw
    assert stored.recipe_updated is False


@pytest.mark.django_db
@patch("groceries.services.gemini_service.fetch_recipe_chat_chile")
def test_recipe_chat_about_recipe_persists_when_model_requests_update(mock_fetch):
    from groceries.gemini_service import RecipeChatFromGemini, RecipeFullFromGemini

    u = _user(username="chat_u2")
    r = Recipe.objects.create(user=u, title="Viejo", notes="notas fijas")
    RecipeIngredient.objects.create(recipe=r, order=0, name="X", amount="")
    RecipeStep.objects.create(recipe=r, order=0, text="Paso viejo.")
    raw = (
        '{"answer": "Actualizado.", "update_recipe": true, '
        '"ingredients": [{"name": "Y", "amount": "100 g"}], "steps": ["Nuevo paso."]}'
    )
    mock_fetch.return_value = RecipeChatFromGemini(
        answer="Actualizado.",
        update_recipe=True,
        updated=RecipeFullFromGemini(
            ingredients=(RecipeIngredientLine(name="Y", amount="100 g"),),
            steps=("Nuevo paso.",),
        ),
        gemini_response_raw=raw,
    )

    out = recipe_chat_about_recipe(
        recipe_id=r.pk,
        user_id=u.pk,
        message="Cambia todo",
    )
    assert out.recipe_updated is True
    row = get_recipe(recipe_id=r.pk, user_id=u.pk)
    assert row.title == "Viejo"
    assert row.notes == "notas fijas"
    assert list(
        row.ingredients.order_by("order").values_list("name", flat=True),
    ) == ["Y"]
    assert list(row.steps.order_by("order").values_list("text", flat=True)) == [
        "Nuevo paso.",
    ]
    stored = RecipeMessage.objects.get(recipe_id=r.pk)
    assert stored.user_message == "Cambia todo"
    assert stored.assistant_answer == "Actualizado."
    assert stored.gemini_response_raw == raw
    assert stored.recipe_updated is True


@pytest.mark.django_db
@patch("groceries.services.gemini_service.fetch_recipe_chat_chile")
def test_recipe_chat_about_recipe_persists_recipe_ops_patch(mock_fetch):
    from groceries.gemini_service import RecipeChatFromGemini

    u = _user(username="chat_ops")
    r = Recipe.objects.create(user=u, title="Arroz", notes="")
    RecipeIngredient.objects.create(recipe=r, order=0, name="Arroz", amount="1 taza")
    RecipeIngredient.objects.create(recipe=r, order=1, name="Agua", amount="2 tazas")
    RecipeStep.objects.create(recipe=r, order=0, text="Hervir.")
    RecipeStep.objects.create(recipe=r, order=1, text="Reposar.")
    raw = (
        '{"answer": "Agregué sal.", "update_recipe": true, '
        '"recipe_ops": [{"op": "insert_ingredient", "index": 2, "name": "Sal", "amount": "1 pizca"}]}'
    )
    mock_fetch.return_value = RecipeChatFromGemini(
        answer="Agregué sal.",
        update_recipe=True,
        updated=None,
        recipe_ops=(
            {
                "op": "insert_ingredient",
                "index": 2,
                "name": "Sal",
                "amount": "1 pizca",
            },
        ),
        gemini_response_raw=raw,
    )

    out = recipe_chat_about_recipe(
        recipe_id=r.pk,
        user_id=u.pk,
        message="Agrega sal al final de ingredientes",
    )
    assert out.recipe_updated is True
    row = get_recipe(recipe_id=r.pk, user_id=u.pk)
    assert list(
        row.ingredients.order_by("order").values_list("name", "amount"),
    ) == [
        ("Arroz", "1 taza"),
        ("Agua", "2 tazas"),
        ("Sal", "1 pizca"),
    ]
    assert list(row.steps.order_by("order").values_list("text", flat=True)) == [
        "Hervir.",
        "Reposar.",
    ]
    stored = RecipeMessage.objects.get(recipe_id=r.pk)
    assert stored.gemini_response_raw == raw


@pytest.mark.django_db
def test_recipe_chat_about_recipe_empty_message_raises():
    u = _user(username="chat_u3")
    r = Recipe.objects.create(user=u, title="T", notes="")
    RecipeIngredient.objects.create(recipe=r, order=0, name="A", amount="")
    RecipeStep.objects.create(recipe=r, order=0, text="S")
    with pytest.raises(ValueError, match="Message"):
        recipe_chat_about_recipe(recipe_id=r.pk, user_id=u.pk, message="   ")


@pytest.mark.django_db
@patch("groceries.services.gemini_service.fetch_recipe_chat_chile")
def test_recipe_chat_about_recipe_wrong_user_raises(mock_fetch):
    u = _user(username="owner_chat")
    other = _user(username="other_chat")
    r = Recipe.objects.create(user=u, title="Mine", notes="")
    RecipeIngredient.objects.create(recipe=r, order=0, name="A", amount="")
    RecipeStep.objects.create(recipe=r, order=0, text="S")
    with pytest.raises(Recipe.DoesNotExist):
        recipe_chat_about_recipe(recipe_id=r.pk, user_id=other.pk, message="Hola")
    mock_fetch.assert_not_called()


@pytest.mark.django_db
@patch("groceries.services.gemini_service.fetch_recipe_chat_chile", return_value=None)
def test_recipe_chat_about_recipe_raises_when_gemini_empty(_mock):
    u = _user(username="chat_u4")
    r = Recipe.objects.create(user=u, title="T", notes="")
    RecipeIngredient.objects.create(recipe=r, order=0, name="A", amount="")
    RecipeStep.objects.create(recipe=r, order=0, text="S")
    with pytest.raises(RecipeGenerationFailedError):
        recipe_chat_about_recipe(recipe_id=r.pk, user_id=u.pk, message="?")
    assert RecipeMessage.objects.filter(recipe_id=r.pk).count() == 0


@pytest.mark.django_db
def test_delete_recipe_wrong_user_raises():
    u = _user(username="owner_del")
    other = _user(username="other_del")
    r = Recipe.objects.create(user=u, title="Mine", notes="")
    RecipeIngredient.objects.create(recipe=r, order=0, name="A", amount="")
    RecipeStep.objects.create(recipe=r, order=0, text="S")
    with pytest.raises(Recipe.DoesNotExist):
        delete_recipe(recipe_id=r.pk, user_id=other.pk)
    assert Recipe.objects.filter(pk=r.pk).exists()


@pytest.mark.django_db
@patch("groceries.services.async_task")
def test_update_recipe_rejects_while_generation_pending(_mock_async):
    u = _user()
    r = create_recipe_from_title_and_notes(title="T", notes="", user_id=u.pk)
    assert r.generation_status == RecipeGenerationStatus.PENDING
    with pytest.raises(ValueError, match="progress"):
        update_recipe(
            recipe_id=r.pk,
            user_id=u.pk,
            title="T",
            notes="",
            ingredient_lines=[("A", "")],
            step_texts=["S"],
        )


@pytest.mark.django_db
def test_update_recipe_replaces_metadata_ingredients_and_steps():
    u = _user(username="chef_edit")
    r = Recipe.objects.create(user=u, title="Old title", notes="old notes")
    RecipeIngredient.objects.create(recipe=r, order=0, name="Salt", amount="pinch")
    RecipeStep.objects.create(recipe=r, order=0, text="Old step.")

    out = update_recipe(
        recipe_id=r.pk,
        user_id=u.pk,
        title="  New title  ",
        notes="  new notes  ",
        ingredient_lines=[
            ("Tomate", "2"),
            ("Cebolla", "1"),
        ],
        step_texts=["Picar.", "Sofreír."],
    )
    assert out.title == "New title"
    assert out.notes == "new notes"
    names = list(out.ingredients.order_by("order").values_list("name", flat=True))
    assert names == ["Tomate", "Cebolla"]
    texts = list(out.steps.order_by("order").values_list("text", flat=True))
    assert texts == ["Picar.", "Sofreír."]
    assert list(out.ingredients.order_by("order").values_list("order", flat=True)) == [0, 1]
    assert list(out.steps.order_by("order").values_list("order", flat=True)) == [0, 1]


@pytest.mark.django_db
def test_update_recipe_wrong_user_raises():
    u = _user(username="owner_r")
    other = _user(username="intruder_r")
    r = Recipe.objects.create(user=u, title="Mine", notes="")
    RecipeIngredient.objects.create(recipe=r, order=0, name="X", amount="")
    RecipeStep.objects.create(recipe=r, order=0, text="Do.")
    with pytest.raises(Recipe.DoesNotExist):
        update_recipe(
            recipe_id=r.pk,
            user_id=other.pk,
            title="Stolen",
            notes="",
            ingredient_lines=[("Y", "")],
            step_texts=["Go."],
        )


@pytest.mark.django_db
def test_update_recipe_requires_nonempty_lists():
    u = _user()
    r = Recipe.objects.create(user=u, title="T", notes="")
    RecipeIngredient.objects.create(recipe=r, order=0, name="A", amount="")
    RecipeStep.objects.create(recipe=r, order=0, text="S")
    with pytest.raises(ValueError, match="ingredient"):
        update_recipe(
            recipe_id=r.pk,
            user_id=u.pk,
            title="T",
            notes="",
            ingredient_lines=[],
            step_texts=["One"],
        )
    with pytest.raises(ValueError, match="step"):
        update_recipe(
            recipe_id=r.pk,
            user_id=u.pk,
            title="T",
            notes="",
            ingredient_lines=[("A", "")],
            step_texts=[],
        )


@pytest.mark.django_db
def test_update_recipe_rejects_blank_ingredient_name_or_step_text():
    u = _user()
    r = Recipe.objects.create(user=u, title="T", notes="")
    RecipeIngredient.objects.create(recipe=r, order=0, name="A", amount="")
    RecipeStep.objects.create(recipe=r, order=0, text="S")
    with pytest.raises(ValueError, match="name"):
        update_recipe(
            recipe_id=r.pk,
            user_id=u.pk,
            title="T",
            notes="",
            ingredient_lines=[("  ", "1")],
            step_texts=["Ok"],
        )
    with pytest.raises(ValueError, match="step"):
        update_recipe(
            recipe_id=r.pk,
            user_id=u.pk,
            title="T",
            notes="",
            ingredient_lines=[("Ok", "")],
            step_texts=["   "],
        )


@pytest.mark.django_db
def test_list_user_recipes_empty():
    u = _user()
    rows, nxt = list_user_recipes(user_id=u.pk)
    assert rows == [] and nxt is None


@pytest.mark.django_db
def test_list_user_recipes_paginates_with_cursor():
    u = _user(username="chef_page")
    base = timezone.now()
    r_old = Recipe.objects.create(user=u, title="old", notes="")
    Recipe.objects.filter(pk=r_old.pk).update(updated_at=base - timedelta(hours=2))
    r_mid = Recipe.objects.create(user=u, title="mid", notes="")
    Recipe.objects.filter(pk=r_mid.pk).update(updated_at=base - timedelta(hours=1))
    r_new = Recipe.objects.create(user=u, title="new", notes="")
    Recipe.objects.filter(pk=r_new.pk).update(updated_at=base)

    p1, cur = list_user_recipes(user_id=u.pk, limit=2)
    assert [r.pk for r in p1] == [r_new.pk, r_mid.pk]
    assert cur is not None

    p2, cur2 = list_user_recipes(user_id=u.pk, limit=2, cursor=cur)
    assert [r.pk for r in p2] == [r_old.pk]
    assert cur2 is None


@pytest.mark.django_db
def test_list_user_recipes_single_select_no_prefetch():
    u = _user()
    Recipe.objects.create(user=u, title="A", notes="")
    with CaptureQueriesContext(connection) as ctx:
        list_user_recipes(user_id=u.pk, limit=10)
    assert len(ctx.captured_queries) == 1


@pytest.mark.django_db
def test_list_user_recipes_rejects_invalid_cursor():
    u = _user()
    with pytest.raises(InvalidRecipeListCursorError):
        list_user_recipes(user_id=u.pk, cursor="not-a-token")


@pytest.mark.django_db
def test_list_user_recipes_rejects_cursor_from_different_user():
    alice = _user(username="alice_r")
    bob = _user(username="bob_r")
    base = timezone.now()
    for i in range(3):
        r = Recipe.objects.create(user=alice, title=f"x{i}", notes="")
        Recipe.objects.filter(pk=r.pk).update(updated_at=base - timedelta(seconds=i))
    _, cur = list_user_recipes(user_id=alice.pk, limit=2)
    assert cur is not None
    with pytest.raises(InvalidRecipeListCursorError):
        list_user_recipes(user_id=bob.pk, cursor=cur)
