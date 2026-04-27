from collections.abc import Iterable

from dateutil.relativedelta import relativedelta
from django.db import transaction
from django.db.models import Count, F, Prefetch
from django.utils import timezone

from groceries.models import Basket, BasketProduct, Product

from .constants import LIST_PURCHASED_BASKETS_LIMIT
from .exceptions import NoOpenBasketError


def get_current_basket(
    *, user_id: int, select_for_update: bool = False
) -> Basket | None:
    """Latest open basket for *user_id* (``purchased_at`` unset), or ``None``."""
    qs = Basket.objects.filter(owner_id=user_id, purchased_at__isnull=True).order_by(
        "-created_at"
    )
    if select_for_update:
        qs = qs.select_for_update()
    return qs.first()


def add_product_to_basket(*, product_id: int, user_id: int) -> Basket:
    """Use latest open basket for *user_id*, or create one; append product."""
    product = Product.objects.get(pk=product_id)
    with transaction.atomic():
        basket = get_current_basket(user_id=user_id, select_for_update=True)
        if basket is None:
            basket = Basket.objects.create(owner_id=user_id)
        basket.products.add(product, through_defaults={"purchase": True})
    return basket


def delete_product_from_basket(
    *,
    product_id: int,
    user_id: int,
    basket_id: int | None = None,
) -> None:
    """Remove product from a basket line.

    *basket_id* ``None``: latest open basket for *user_id* (raises
    :class:`NoOpenBasketError` if none). No-op if product not in that basket.

    *basket_id* set: that basket must belong to *user_id* and have
    ``purchased_at`` set (past checkout). No-op if product not in that basket.
    """
    product = Product.objects.get(pk=product_id)
    with transaction.atomic():
        if basket_id is None:
            basket = get_current_basket(user_id=user_id, select_for_update=True)
            if basket is None:
                raise NoOpenBasketError()
        else:
            basket = Basket.objects.select_for_update().get(
                pk=basket_id,
                owner_id=user_id,
            )
            if basket.purchased_at is None:
                msg = "Only past (purchased) baskets support delete by basket_id."
                raise ValueError(msg)
        basket.products.remove(product)


def set_product_purchase_in_open_basket(
    *,
    product_id: int,
    user_id: int,
    purchase: bool,
) -> Basket:
    """Set ``purchase`` flag on a line in user's latest open basket."""
    Product.objects.get(pk=product_id)
    with transaction.atomic():
        basket = get_current_basket(user_id=user_id, select_for_update=True)
        if basket is None:
            raise NoOpenBasketError()
        n = BasketProduct.objects.filter(
            basket_id=basket.pk,
            product_id=product_id,
        ).update(purchase=purchase)
        if n == 0:
            msg = "Product is not in the current basket."
            raise ValueError(msg)
    return basket


def basket_product_lines(*, basket_id: int) -> list[tuple[Product, bool]]:
    """Products in *basket_id* ordered by name, pk; with line ``purchase`` flag."""
    rows = (
        BasketProduct.objects.filter(basket_id=basket_id)
        .select_related("product")
        .order_by("product__name", "product__pk")
    )
    return [(r.product, r.purchase) for r in rows]


def get_current_basket_with_products(*, user_id: int) -> Basket | None:
    """Latest open basket for *user_id* with prefetched products, or ``None``."""
    qs = Basket.objects.filter(owner_id=user_id, purchased_at__isnull=True).order_by(
        "-created_at"
    )
    return (
        qs.prefetch_related(
            Prefetch("products", queryset=Product.objects.order_by("name", "pk")),
        ).first()
    )


def list_purchased_baskets(*, user_id: int) -> list[Basket]:
    """Up to :data:`LIST_PURCHASED_BASKETS_LIMIT` baskets with ``purchased_at`` set, newest first.

    Prefetch uses ``Product.all_objects`` so lines include soft-deleted catalog rows.
    """
    purchased_product_qs = Product.all_objects.order_by("name", "pk")
    return list(
        Basket.objects.filter(owner_id=user_id, purchased_at__isnull=False)
        .prefetch_related(
            Prefetch("products", queryset=purchased_product_qs),
        )
        .order_by("-purchased_at", "-pk")[:LIST_PURCHASED_BASKETS_LIMIT]
    )


def list_purchased_baskets_for_running_low(*, user_id: int) -> list[Basket]:
    """Purchased baskets in last two calendar months (by ``purchased_at``), newest first.

    Used for Gemini running-low sync; no row cap (window bounds size).
    Prefetch uses active ``Product.objects`` only — soft-deleted catalog rows omitted from history.
    Lines omit products with ``purchase_count`` below 2 so first-time buys never go to Gemini.
    """
    since = timezone.now() - relativedelta(months=2)
    purchased_product_qs = Product.objects.filter(purchase_count__gte=2).order_by(
        "name",
        "pk",
    )
    return list(
        Basket.objects.filter(
            owner_id=user_id,
            purchased_at__isnull=False,
            purchased_at__gte=since,
        )
        .prefetch_related(
            Prefetch("products", queryset=purchased_product_qs),
        )
        .order_by("-purchased_at", "-pk")
    )


def recalculate_product_purchase_counts_from_baskets(
    *,
    product_ids: Iterable[int] | None = None,
) -> int:
    """Set ``purchase_count`` from ``BasketProduct`` rows where basket has ``purchased_at`` and ``purchase`` is True.

    Matches checkout semantics in :func:`purchase_latest_open_basket` / migration backfill.

    When *product_ids* is ``None``, every catalog row (including soft-deleted) is set:
    products with no matching lines get ``purchase_count`` 0.

    Returns number of ``Product`` rows updated (same as considered rows).
    """
    base = BasketProduct.objects.filter(
        basket__purchased_at__isnull=False,
        purchase=True,
    )
    if product_ids is not None:
        id_set = list(product_ids)
        if not id_set:
            return 0
        base = base.filter(product_id__in=id_set)
        counts = {
            row["product_id"]: row["n"]
            for row in base.values("product_id").annotate(n=Count("id"))
        }
        products = list(Product.all_objects.filter(pk__in=id_set))
        for p in products:
            p.purchase_count = counts.get(p.pk, 0)
        Product.all_objects.bulk_update(products, ["purchase_count"], batch_size=500)
        return len(products)

    counts = {
        row["product_id"]: row["n"]
        for row in base.values("product_id").annotate(n=Count("id"))
    }
    Product.all_objects.update(purchase_count=0)
    if not counts:
        return Product.all_objects.count()
    products = list(Product.all_objects.filter(pk__in=counts))
    for p in products:
        p.purchase_count = counts[p.pk]
    Product.all_objects.bulk_update(products, ["purchase_count"], batch_size=500)
    return Product.all_objects.count()


def purchase_latest_open_basket(*, user_id: int) -> Basket:
    """Set purchased_at on user's latest open basket.

    Lines with ``purchase`` False are removed from this basket, attached to a new
    open basket, and excluded from purchase_count for this checkout.
    """
    with transaction.atomic():
        basket = get_current_basket(user_id=user_id, select_for_update=True)
        if basket is None:
            raise NoOpenBasketError()
        deferred_ids = list(
            BasketProduct.objects.filter(basket_id=basket.pk, purchase=False).values_list(
                "product_id",
                flat=True,
            )
        )
        if deferred_ids:
            carry = Basket.objects.create(owner_id=user_id)
            BasketProduct.objects.filter(
                basket_id=basket.pk,
                product_id__in=deferred_ids,
            ).update(basket_id=carry.pk)
        purchase_ids = list(
            BasketProduct.objects.filter(basket_id=basket.pk, purchase=True).values_list(
                "product_id",
                flat=True,
            )
        )
        basket.purchased_at = timezone.now()
        basket.save(update_fields=["purchased_at"])
        if purchase_ids:
            Product.objects.filter(pk__in=purchase_ids).update(
                purchase_count=F("purchase_count") + 1,
                running_low=False,
                running_low_snoozed_until=None,
            )
    return basket


def purchase_single_product(*, product_id: int, user_id: int) -> Basket:
    """Create new basket with one product, mark purchased immediately.

    If that product is already in user's current open basket, removes it there first.
    Other lines in that basket unchanged (instant checkout path).
    """
    product = Product.objects.get(pk=product_id, user_id=user_id)
    with transaction.atomic():
        open_basket = get_current_basket(user_id=user_id, select_for_update=True)
        if open_basket is not None and open_basket.products.filter(pk=product_id).exists():
            open_basket.products.remove(product)
        basket = Basket.objects.create(owner_id=user_id)
        basket.products.add(product, through_defaults={"purchase": True})
        basket.purchased_at = timezone.now()
        basket.save(update_fields=["purchased_at"])
        Product.objects.filter(pk=product.pk).update(
            purchase_count=F("purchase_count") + 1,
            running_low=False,
            running_low_snoozed_until=None,
        )
    return basket
