from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from groceries.models import (
    Basket,
    BasketProduct,
    Product,
)
from groceries.tests.services.conftest import catalog_product, user as _user
from groceries.services import (
    LIST_PURCHASED_BASKETS_LIMIT,
    NoOpenBasketError,
    add_product_to_basket,
    basket_product_lines,
    delete_product,
    delete_product_from_basket,
    get_current_basket,
    get_current_basket_with_products,
    list_purchased_baskets,
    purchase_latest_open_basket,
    purchase_single_product,
    recalculate_product_purchase_counts_from_baskets,
    set_product_purchase_in_open_basket,
)

User = get_user_model()


@pytest.mark.django_db
def test_add_product_to_basket_creates_basket_when_none_open():
    user = _user()
    pid = catalog_product("Milk").pk
    basket = add_product_to_basket(product_id=pid, user_id=user.pk)
    assert basket.pk is not None
    assert basket.purchased_at is None
    assert list(basket.products.values_list("pk", flat=True)) == [pid]


@pytest.mark.django_db
def test_add_product_to_basket_reuses_latest_open_basket():
    user = _user()
    pid_a = catalog_product("A").pk
    pid_b = catalog_product("B").pk
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
    pid = catalog_product("Milk").pk
    basket = add_product_to_basket(product_id=pid, user_id=user.pk)
    row = BasketProduct.objects.get(basket_id=basket.pk, product_id=pid)
    assert row.purchase is True


@pytest.mark.django_db
def test_add_product_to_basket_skips_purchased_baskets():
    user = _user()
    p = catalog_product("X").pk
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
    pid = catalog_product("Milk").pk
    add_product_to_basket(product_id=pid, user_id=user.pk)
    delete_product_from_basket(product_id=pid, user_id=user.pk)
    b = Basket.objects.get(owner=user, purchased_at__isnull=True)
    assert b.products.count() == 0


@pytest.mark.django_db
def test_delete_product_from_basket_targets_latest_open_basket():
    user = _user()
    pid = catalog_product("X").pk
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
    pid = catalog_product("Y").pk
    Basket.objects.create(owner=user)
    delete_product_from_basket(product_id=pid, user_id=user.pk)
    assert (
        Basket.objects.get(owner=user, purchased_at__isnull=True).products.count() == 0
    )


@pytest.mark.django_db
def test_delete_product_from_basket_raises_when_no_open_basket():
    user = _user()
    pid = catalog_product("Z").pk
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
    pid = catalog_product("Past").pk
    past = Basket.objects.create(owner=user, purchased_at=timezone.now())
    past.products.add(pid)
    delete_product_from_basket(product_id=pid, user_id=user.pk, basket_id=past.pk)
    past.refresh_from_db()
    assert past.products.count() == 0


@pytest.mark.django_db
def test_delete_product_from_basket_purchased_noop_when_product_absent():
    user = _user()
    pid = catalog_product("Solo").pk
    past = Basket.objects.create(owner=user, purchased_at=timezone.now())
    delete_product_from_basket(product_id=pid, user_id=user.pk, basket_id=past.pk)
    assert past.products.count() == 0


@pytest.mark.django_db
def test_delete_product_from_basket_by_id_raises_when_open_basket():
    user = _user()
    pid = catalog_product("Open").pk
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
    pid = catalog_product("Mine").pk
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
    pid_a = catalog_product("Apple").pk
    pid_b = catalog_product("Banana").pk
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
    pid = catalog_product("Z").pk
    b = Basket.objects.create(owner=user, purchased_at=timezone.now())
    b.products.add(pid)
    assert get_current_basket_with_products(user_id=user.pk) is None


@pytest.mark.django_db
def test_get_current_basket_with_products_prefers_open_when_newer_is_purchased():
    user = _user()
    pid_open = catalog_product("Open").pk
    pid_bought = catalog_product("Bought").pk
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
    p = catalog_product("Shared catalog item").pk
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
def test_list_purchased_baskets_caps_at_five_newest_by_purchased_at():
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

