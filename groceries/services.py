import base64
import json
import logging
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.db.models import F, Prefetch, Q
from django.utils import timezone

from groceries import gemini_service
from groceries.gemini_service import MerchantProductInfo, RunningLowSuggestion
from groceries.models import Basket, Product
from groceries.schemas import ProductCandidateSchema

logger = logging.getLogger(__name__)


class InvalidProductListCursorError(Exception):
    """Cursor token invalid or used with wrong parameters."""

    def __init__(self, message: str = "Invalid cursor.") -> None:
        super().__init__(message)


class NoOpenBasketError(Exception):
    """No basket with purchased_at unset exists."""

    def __init__(self, message: str = "No open basket.") -> None:
        super().__init__(message)


DEFAULT_LIST_LIMIT = 20
MAX_LIST_LIMIT = 100
LIST_PURCHASED_BASKETS_LIMIT = 5


def _fetch_merchant_product_info_by_identity_or_none(
    *,
    standard_name: str,
    brand: str,
    format: str,
    product_id: int,
) -> MerchantProductInfo | None:
    try:
        return gemini_service.fetch_merchant_product_info_by_identity(
            standard_name=standard_name,
            brand=brand,
            format=format,
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
    product.price = info.price
    product.save(update_fields=["price"])


def find_product_candidates(*, query: str) -> list[MerchantProductInfo]:
    """Return up to 10 Gemini merchant product rows for *query*; no DB writes."""
    normalized = query.strip()
    if not normalized:
        msg = "Query must not be empty."
        raise ValueError(msg)
    try:
        return gemini_service.fetch_merchant_product_candidates(query=normalized)
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

    Ordered by purchase count (highest first), then name, then primary key.

    Excludes products already in *user_id*'s current open basket (same basket as add/remove).
    """
    lim = _clamp_limit(limit)
    q = (search or "").strip()

    qs = Product.objects.all().order_by("-purchase_count", "name", "pk")
    if q:
        qs = qs.filter(name__icontains=q)

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
        basket.products.add(product)
    return basket


def delete_product_from_basket(*, product_id: int, user_id: int) -> None:
    """Remove product from user's latest open basket. No-op if not in basket."""
    product = Product.objects.get(pk=product_id)
    with transaction.atomic():
        basket = get_current_basket(user_id=user_id, select_for_update=True)
        if basket is None:
            raise NoOpenBasketError()
        basket.products.remove(product)


def get_current_basket_with_products(*, user_id: int) -> Basket | None:
    """Newest basket for *user* by created_at (any purchase state)."""
    return (
        Basket.objects.filter(owner_id=user_id)
        .prefetch_related(
            Prefetch("products", queryset=Product.objects.order_by("name", "pk")),
        )
        .order_by("-created_at")
        .first()
    )


def list_purchased_baskets(*, user_id: int) -> list[Basket]:
    """Up to :data:`LIST_PURCHASED_BASKETS_LIMIT` baskets with ``purchased_at`` set, newest first."""
    return list(
        Basket.objects.filter(owner_id=user_id, purchased_at__isnull=False)
        .prefetch_related(
            Prefetch("products", queryset=Product.objects.order_by("name", "pk")),
        )
        .order_by("-purchased_at", "-pk")[:LIST_PURCHASED_BASKETS_LIMIT]
    )


def basket_total_price(*, basket: Basket) -> Decimal:
    """Sum of ``Product.price`` for lines in *basket*.

    Uses in-memory sum over ``basket.products.all()`` — pair with
    :func:`get_current_basket_with_products` (prefetch) to avoid extra queries.
    """
    total = Decimal("0")
    for p in basket.products.all():
        total += p.price
    return total


def purchase_latest_open_basket(*, user_id: int) -> Basket:
    """Set purchased_at on user's latest open basket."""
    with transaction.atomic():
        basket = get_current_basket(user_id=user_id, select_for_update=True)
        if basket is None:
            raise NoOpenBasketError()
        product_ids = list(basket.products.values_list("pk", flat=True))
        basket.purchased_at = timezone.now()
        basket.save(update_fields=["purchased_at"])
        if product_ids:
            Product.objects.filter(pk__in=product_ids).update(
                purchase_count=F("purchase_count") + 1
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
            bit = f"- {em + ' ' if em else ''}{name}"
            if fmt:
                bit += f" — {fmt}"
            lines.append(bit)
        lines.append("")
    return "\n".join(lines).strip()


def suggest_running_low_products(*, user_id: int) -> list[RunningLowSuggestion]:
    """Ask Gemini which products may run low soon, from up to 5 newest purchased baskets."""
    baskets = list_purchased_baskets(user_id=user_id)
    if not baskets:
        return []
    block = _format_purchased_baskets_for_running_low(baskets)
    try:
        return gemini_service.suggest_running_low_from_purchase_history(
            history_markdown=block,
        )
    except RuntimeError:
        logger.warning(
            "Skipped Gemini running-low suggestions: GEMINI_API_KEY not set (user id=%s).",
            user_id,
        )
    except Exception:
        logger.exception(
            "Gemini running-low suggestions failed for user id=%s",
            user_id,
        )
    return []
