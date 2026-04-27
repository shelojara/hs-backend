from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from groceries.gemini_service import (
    RunningLowSuggestion,
)
from groceries.models import (
    Basket,
    Product,
)
from groceries.tests.services.conftest import catalog_product, user as _user
from groceries.services import (
    delete_product,
    list_purchased_baskets_for_running_low,
    running_low_sync_user_ids,
    sync_running_low_flags_for_user,
)

User = get_user_model()


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.suggest_running_low_from_purchase_history",
)
def test_sync_running_low_skips_snoozed_product(mock_suggest):
    utc = ZoneInfo("UTC")
    user = _user(username="snooze_rl")
    milk = catalog_product("Milk", owner=user)
    jam = catalog_product("Jam", owner=user)
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
    milk = catalog_product("Milk", owner=user)
    jam = catalog_product("Jam", owner=user)
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
    milk = catalog_product("Milk", owner=user)
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
    user = _user(username="snooze_exp")
    milk = catalog_product("Milk", owner=user)
    Product.objects.filter(pk=milk.pk).update(purchase_count=2)
    b = Basket.objects.create(owner=user, purchased_at=timezone.now())
    b.products.add(milk)
    Product.objects.filter(pk=milk.pk).update(
        running_low_snoozed_until=datetime(2026, 5, 1, 12, 0, 0, tzinfo=utc),
    )
    with patch("groceries.services.timezone.now") as mock_now:
        mock_now.return_value = datetime(2026, 5, 2, 12, 0, 0, tzinfo=utc)
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
    milk = catalog_product("Milk", owner=user)
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
    old_milk = catalog_product("Old milk", owner=user)
    Product.objects.filter(pk=old_milk.pk).update(purchase_count=2)
    new_jam = catalog_product("Jam", owner=user)
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
    p = catalog_product("X", owner=user)
    Product.objects.filter(pk=p.pk).update(running_low=True)
    sync_running_low_flags_for_user(user_id=user.pk)
    assert not Product.objects.get(pk=p.pk).running_low


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.suggest_running_low_from_purchase_history",
)
def test_sync_running_low_calls_gemini_and_sets_flags(mock_suggest):
    mock_suggest.return_value = [
        RunningLowSuggestion(
            product_name="Leche",
            reason="Última compra hace tiempo.",
            urgency="medium",
            product_ids=(999,),
        ),
    ]
    user = _user(username="runlow")
    milk = catalog_product("Leche entera", owner=user)
    Product.objects.filter(pk=milk.pk).update(purchase_count=2)
    b = Basket.objects.create(owner=user, purchased_at=timezone.now())
    b.products.add(milk)

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
    sync_running_low_flags_for_user(user_id=user.pk)
    assert Product.objects.get(pk=milk.pk).running_low


@pytest.mark.django_db
@patch("groceries.services.running_low.send_email_via_gmail")
@patch(
    "groceries.services.gemini_service.suggest_running_low_from_purchase_history",
)
def test_sync_running_low_sends_digest_email_still_and_new(mock_suggest, mock_mail):
    user = _user(username="digest", email="shopper@example.com")
    milk = catalog_product("Leche entera", owner=user)
    bread = catalog_product("Pan integral", owner=user)
    Product.objects.filter(pk__in=[milk.pk, bread.pk]).update(purchase_count=2)
    Product.objects.filter(pk=milk.pk).update(running_low=True)
    b = Basket.objects.create(owner=user, purchased_at=timezone.now())
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
@patch("groceries.services.running_low.send_email_via_gmail")
@patch(
    "groceries.services.gemini_service.suggest_running_low_from_purchase_history",
)
def test_sync_running_low_skips_email_when_user_has_no_email(mock_suggest, mock_mail):
    user = _user(username="noaddr", email="")
    milk = catalog_product("Leche", owner=user)
    Product.objects.filter(pk=milk.pk).update(purchase_count=2)
    b = Basket.objects.create(owner=user, purchased_at=timezone.now())
    b.products.add(milk)
    mock_suggest.return_value = [
        RunningLowSuggestion(
            product_name="Leche",
            reason="x.",
            urgency="medium",
            product_ids=(milk.pk,),
        ),
    ]

    sync_running_low_flags_for_user(user_id=user.pk)

    mock_mail.assert_not_called()


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.suggest_running_low_from_purchase_history",
    side_effect=RuntimeError("no key"),
)
def test_sync_running_low_clears_when_gemini_unconfigured(_mock_suggest):
    user = _user(username="nokey")
    milk = catalog_product("Leche", owner=user)
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
    catalog_product("p", owner=a)
    catalog_product("p2", owner=a)
    catalog_product("q", owner=b)
    uids = running_low_sync_user_ids()
    assert sorted(uids) == sorted([a.pk, b.pk])
