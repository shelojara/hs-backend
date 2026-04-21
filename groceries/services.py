import base64
import json
import logging
from decimal import Decimal
from typing import Any

from dateutil.relativedelta import relativedelta

from django.db import transaction
from django.db.models import F, Max, Prefetch, Q
from django.utils import timezone

from groceries import gemini_service
from groceries.favicon_service import fetch_favicon_url, normalize_website_url
from groceries.gemini_service import MerchantProductInfo, PreferredMerchantContext
from groceries.url_page_context import fetch_page_text_for_product_context, is_http_https_url
from groceries.models import (
    Basket,
    BasketProduct,
    Merchant,
    Product,
    Search,
    SearchStatus,
    Whiteboard,
)
from groceries.schemas import ProductCandidateSchema, WhiteboardLineSchema

logger = logging.getLogger(__name__)


def _preferred_merchant_context_for_user(user_id: int) -> list[PreferredMerchantContext]:
    rows = Merchant.objects.filter(user_id=user_id).order_by(
        "preference_order",
        "pk",
    )
    return [
        PreferredMerchantContext(name=m.name, website=m.website)
        for m in rows
    ]


class InvalidProductListCursorError(Exception):
    """Cursor token invalid or used with wrong parameters."""

    def __init__(self, message: str = "Invalid cursor.") -> None:
        super().__init__(message)


class NoOpenBasketError(Exception):
    """No basket with purchased_at unset exists."""

    def __init__(self, message: str = "No open basket.") -> None:
        super().__init__(message)


DEFAULT_LIST_LIMIT = 50
MAX_LIST_LIMIT = 100
LIST_PURCHASED_BASKETS_LIMIT = 5


def _fetch_merchant_product_info_by_identity_or_none(
    *,
    standard_name: str,
    brand: str,
    format: str,
    product_id: int,
    user_id: int,
) -> MerchantProductInfo | None:
    try:
        return gemini_service.fetch_merchant_product_info_by_identity(
            standard_name=standard_name,
            brand=brand,
            format=format,
            preferred_merchants=_preferred_merchant_context_for_user(user_id),
        )
    except RuntimeError:
        logger.warning(
            "Skipped Gemini merchant product info by identity: GEMINI_API_KEY not set (product id=%s).",
            product_id,
        )
    except Exception:
        logger.exception(
            "Gemini merchant product info by identity failed for product id=%s",
            product_id,
        )
    return None


def _apply_merchant_price_only(product: Product, info: MerchantProductInfo) -> None:
    if info.price is None:
        return
    product.price = info.price
    product.save(update_fields=["price"])


def find_product_candidates(
    *,
    query: str,
    user_id: int,
) -> list[MerchantProductInfo]:
    """Return up to 20 Gemini merchant product rows for *query*; no DB writes."""
    normalized = query.strip()
    if not normalized:
        msg = "Query must not be empty."
        raise ValueError(msg)
    page_context: str | None = None
    if is_http_https_url(normalized):
        page_context = fetch_page_text_for_product_context(normalized)
    try:
        return gemini_service.fetch_merchant_product_candidates(
            query=normalized,
            preferred_merchants=_preferred_merchant_context_for_user(user_id),
            page_context=page_context,
        )
    except RuntimeError:
        logger.warning(
            "Skipped Gemini find product candidates: GEMINI_API_KEY not set.",
        )
    except Exception:
        logger.exception(
            "Gemini find product candidates failed for query=%r",
            normalized,
        )
    return []


def create_product_from_candidate(
    *,
    candidate: ProductCandidateSchema,
    user_id: int,
    is_custom: bool = False,
) -> int:
    """Persist product from merchant candidate fields (no Gemini call)."""
    product = Product.objects.create(
        name=candidate.name,
        standard_name=candidate.standard_name,
        brand=candidate.brand,
        price=candidate.price,
        format=candidate.format,
        emoji=candidate.emoji,
        is_custom=is_custom,
        user_id=user_id,
    )
    return product.pk


def update_product(
    *,
    product_id: int,
    user_id: int,
    standard_name: str,
    brand: str,
    format: str,
    price: Decimal | None,
    emoji: str,
) -> Product:
    """Update persisted merchant fields; no Gemini call."""
    product = Product.objects.get(pk=product_id, user_id=user_id)
    product.standard_name = standard_name
    product.brand = brand
    product.format = format
    product.price = price
    product.emoji = emoji
    product.save(
        update_fields=["standard_name", "brand", "format", "price", "emoji"],
    )
    return product


def delete_product(*, product_id: int, user_id: int) -> None:
    """Soft-delete product owned by *user_id*; drop line from current open basket only."""
    product = Product.objects.get(pk=product_id, user_id=user_id)
    now = timezone.now()
    with transaction.atomic():
        basket = get_current_basket(user_id=user_id, select_for_update=True)
        if basket is not None and basket.products.filter(pk=product.pk).exists():
            basket.products.remove(product)
        product.deleted_at = now
        product.save(update_fields=["deleted_at"])


def recheck_product_price(*, product_id: int, user_id: int) -> Product:
    """Refresh *price* from Gemini using *product*'s standard_name, brand, format (identity prompt).

    Does not change name, brand, format, emoji, or standard_name.

    Raises Product.DoesNotExist when no row matches *product_id* and *user_id*.
    Raises ValueError when stored *standard_name* is blank (identity lookup needs it).
    """
    product = Product.objects.get(pk=product_id, user_id=user_id)
    sn = (product.standard_name or "").strip()
    if not sn:
        msg = "Product has no standard_name; cannot recheck price."
        raise ValueError(msg)
    br = (product.brand or "").strip()
    fmt = (product.format or "").strip()
    info = _fetch_merchant_product_info_by_identity_or_none(
        standard_name=sn,
        brand=br,
        format=fmt,
        product_id=product.pk,
        user_id=user_id,
    )
    if info:
        _apply_merchant_price_only(product, info)
    return product


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def _encode_cursor(payload: dict[str, Any]) -> str:
    return _b64url_encode(json.dumps(payload, separators=(",", ":")).encode())


def _decode_cursor(token: str) -> dict[str, Any]:
    try:
        return json.loads(_b64url_decode(token).decode())
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise InvalidProductListCursorError() from exc


def _clamp_limit(limit: int) -> int:
    if limit < 1:
        return 1
    return min(limit, MAX_LIST_LIMIT)


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


def list_products(
    *,
    user_id: int,
    limit: int = DEFAULT_LIST_LIMIT,
    cursor: str | None = None,
    search: str | None = None,
) -> tuple[list[Product], str | None]:
    """List products with cursor pagination; optional case-insensitive substring search (ILIKE).

    Search matches *name* or *brand* when non-empty.

    Ordered by purchase count (highest first), then name, then primary key.

    Excludes products already in *user_id*'s current open basket (same basket as add/remove).
    """
    lim = _clamp_limit(limit)
    q = (search or "").strip()

    qs = Product.objects.all().order_by("-purchase_count", "name", "pk")
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(brand__icontains=q))

    basket = get_current_basket(user_id=user_id)
    if basket is not None:
        cart_pks = list(basket.products.values_list("pk", flat=True))
        if cart_pks:
            qs = qs.exclude(pk__in=cart_pks)

    if cursor:
        payload = _decode_cursor(cursor)
        try:
            cq = payload["q"]
            c_count = int(payload["c"])
            cname = payload["n"]
            cpk = int(payload["i"])
            cu = payload.get("u")
        except (KeyError, TypeError, ValueError) as exc:
            raise InvalidProductListCursorError() from exc
        if cq != q:
            raise InvalidProductListCursorError(
                "Cursor does not match request parameters."
            )
        if cu != user_id:
            raise InvalidProductListCursorError(
                "Cursor does not match request parameters."
            )
        qs = qs.filter(
            Q(purchase_count__lt=c_count)
            | Q(purchase_count=c_count, name__gt=cname)
            | Q(purchase_count=c_count, name=cname, pk__gt=cpk)
        )

    rows = list(qs[: lim + 1])
    has_more = len(rows) > lim
    page = rows[:lim]

    next_cursor = None
    if has_more and page:
        last = page[-1]
        next_cursor = _encode_cursor(
            {
                "q": q,
                "c": last.purchase_count,
                "n": last.name,
                "i": last.pk,
                "u": user_id,
            }
        )
    return page, next_cursor


def add_product_to_basket(*, product_id: int, user_id: int) -> Basket:
    """Use latest open basket for *user_id*, or create one; append product."""
    product = Product.objects.get(pk=product_id)
    with transaction.atomic():
        basket = get_current_basket(user_id=user_id, select_for_update=True)
        if basket is None:
            basket = Basket.objects.create(owner_id=user_id)
        basket.products.add(product, through_defaults={"purchase": True})
    return basket


def delete_product_from_basket(*, product_id: int, user_id: int) -> None:
    """Remove product from user's latest open basket. No-op if not in basket."""
    product = Product.objects.get(pk=product_id)
    with transaction.atomic():
        basket = get_current_basket(user_id=user_id, select_for_update=True)
        if basket is None:
            raise NoOpenBasketError()
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
    """
    since = timezone.now() - relativedelta(months=2)
    purchased_product_qs = Product.objects.order_by("name", "pk")
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
        )
    return basket


def _format_purchased_baskets_for_running_low(baskets: list[Basket]) -> str:
    """Build plain-text block of basket history for Gemini (newest first)."""
    lines: list[str] = []
    for bi, basket in enumerate(baskets, start=1):
        ts = basket.purchased_at
        ts_label = ts.isoformat() if ts else ""
        lines.append(f"## Basket {bi} (purchased_at: {ts_label})")
        products = list(basket.products.all())
        if not products:
            lines.append("(empty)")
            continue
        for p in products:
            fmt = (p.format or "").strip()
            em = (p.emoji or "").strip()
            name = (p.name or "").strip()
            bit = f"- [product_id={p.pk}] {em + ' ' if em else ''}{name}"
            if fmt:
                bit += f" — {fmt}"
            lines.append(bit)
        lines.append("")
    return "\n".join(lines).strip()


def sync_running_low_flags_for_user(*, user_id: int) -> None:
    """Set ``Product.running_low`` from Gemini, using purchases from last two months.

    Clears ``running_low`` for all of the user's products first, then sets it for ids
    returned in model suggestions (matched to this user's product rows).
    """
    Product.objects.filter(user_id=user_id).update(running_low=False)
    baskets = list_purchased_baskets_for_running_low(user_id=user_id)
    if not baskets:
        return
    block = _format_purchased_baskets_for_running_low(baskets)
    try:
        suggestions = gemini_service.suggest_running_low_from_purchase_history(
            history_markdown=block,
        )
    except RuntimeError:
        logger.warning(
            "Skipped Gemini running-low sync: GEMINI_API_KEY not set (user id=%s).",
            user_id,
        )
        return
    except Exception:
        logger.exception(
            "Gemini running-low sync failed for user id=%s",
            user_id,
        )
        return
    pids: set[int] = set()
    for s in suggestions:
        for pid in s.product_ids:
            if pid > 0:
                pids.add(pid)
    if not pids:
        return
    Product.objects.filter(user_id=user_id, pk__in=pids).update(running_low=True)


def running_low_sync_user_ids() -> list[int]:
    """Distinct user ids that own at least one active (non-soft-deleted) product."""
    return list(
        Product.objects.order_by()
        .values_list("user_id", flat=True)
        .distinct(),
    )


def save_whiteboard(*, user_id: int, lines: list[WhiteboardLineSchema]) -> None:
    """Upsert single whiteboard JSON for user."""
    payload = [line.model_dump() for line in lines]
    Whiteboard.objects.update_or_create(
        user_id=user_id,
        defaults={"data": payload},
    )


def get_whiteboard(*, user_id: int) -> list[WhiteboardLineSchema]:
    """Return persisted lines, or empty list if never saved."""
    try:
        row = Whiteboard.objects.get(user_id=user_id)
    except Whiteboard.DoesNotExist:
        return []
    return [WhiteboardLineSchema.model_validate(item) for item in row.data]


def list_user_merchants(*, user_id: int) -> list[Merchant]:
    """Preferred merchants for *user_id*, ordered by preference (then pk)."""
    return list(
        Merchant.objects.filter(user_id=user_id).order_by("preference_order", "pk"),
    )


def create_user_merchant(*, user_id: int, name: str, website: str) -> Merchant:
    """Persist a merchant and resolve ``favicon_url`` from *website*."""
    label = name.strip()
    if not label:
        msg = "Merchant name must not be empty."
        raise ValueError(msg)
    normalized = normalize_website_url(website)
    fav = fetch_favicon_url(website) or ""
    agg = Merchant.objects.filter(user_id=user_id).aggregate(m=Max("preference_order"))
    next_order = (agg["m"] if agg["m"] is not None else -1) + 1
    return Merchant.objects.create(
        user_id=user_id,
        name=label,
        website=normalized,
        favicon_url=fav,
        preference_order=next_order,
    )


def update_user_merchant(
    *,
    user_id: int,
    merchant_id: int,
    name: str,
    website: str,
) -> Merchant:
    """Update merchant fields and refresh favicon when *website* changes."""
    label = name.strip()
    if not label:
        msg = "Merchant name must not be empty."
        raise ValueError(msg)
    merchant = Merchant.objects.get(pk=merchant_id, user_id=user_id)
    normalized = normalize_website_url(website)
    merchant.name = label
    merchant.website = normalized
    merchant.favicon_url = fetch_favicon_url(website) or ""
    merchant.save()
    return merchant


def delete_user_merchant(*, user_id: int, merchant_id: int) -> None:
    """Delete a merchant owned by *user_id*."""
    merchant = Merchant.objects.get(pk=merchant_id, user_id=user_id)
    merchant.delete()


def _gemini_search_candidate_dicts(*, query: str, user_id: int) -> list[dict]:
    """Gemini + Google Search product rows as JSON-serializable dicts.

    ``RuntimeError`` (missing API key) → ``[]``. Other exceptions propagate so the
    caller can mark the job failed.
    """
    normalized = (query or "").strip()
    if not normalized:
        return []
    page_context: str | None = None
    if is_http_https_url(normalized):
        page_context = fetch_page_text_for_product_context(normalized)
    try:
        rows = gemini_service.fetch_merchant_product_candidates(
            query=normalized,
            preferred_merchants=_preferred_merchant_context_for_user(user_id),
            page_context=page_context,
        )
    except RuntimeError:
        logger.warning(
            "Skipped Gemini async search: GEMINI_API_KEY not set (user id=%s).",
            user_id,
        )
        return []
    return gemini_service.search_result_rows_from_merchant_products(rows)


def create_search(*, query: str, user_id: int) -> int:
    """Persist pending ``Search`` and enqueue background Gemini search; return id."""
    q = (query or "").strip()
    if not q:
        msg = "Query must not be empty."
        raise ValueError(msg)
    from groceries import scheduled_tasks

    row = Search.objects.create(user_id=user_id, query=q, status=SearchStatus.PENDING)
    scheduled_tasks.enqueue_search_job(row.id)
    return row.id


def run_search_background(search_id: int) -> None:
    """Worker: load ``Search``, call Gemini, set ``result_candidates`` and status."""
    try:
        search = Search.objects.get(pk=search_id)
    except Search.DoesNotExist:
        logger.warning("run_search_background: Search id=%s missing", search_id)
        return

    if search.status != SearchStatus.PENDING:
        return

    try:
        candidates = _gemini_search_candidate_dicts(
            query=search.query,
            user_id=search.user_id,
        )
    except Exception:
        logger.exception("Gemini search failed for search id=%s", search_id)
        Search.objects.filter(pk=search_id).update(
            status=SearchStatus.FAILED,
            completed_at=timezone.now(),
        )
        return

    Search.objects.filter(pk=search_id).update(
        status=SearchStatus.COMPLETED,
        result_candidates=candidates,
        completed_at=timezone.now(),
    )
