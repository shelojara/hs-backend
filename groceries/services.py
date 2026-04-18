import base64
import json
import logging
from decimal import Decimal
from typing import Any

from django.db import IntegrityError, transaction
from django.db.models import Prefetch, Q
from django.utils import timezone

from groceries import gemini_service
from groceries.gemini_service import LiderProductInfo
from groceries.models import Basket, Product

logger = logging.getLogger(__name__)


class ProductNameConflict(Exception):
    """Another product already uses this name (case-insensitive)."""

    def __init__(self, message: str = "A product with this name already exists.") -> None:
        super().__init__(message)


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

_GEMINI_SUGGESTED_NAME_CONFLICT = (
    "Another product already uses the name suggested by Gemini."
)


def _fetch_lider_product_info_or_none(*, product_name: str, product_id: int) -> LiderProductInfo | None:
    try:
        return gemini_service.fetch_lider_product_info(product_name=product_name)
    except RuntimeError:
        logger.warning(
            "Skipped Gemini Líder product info: GEMINI_API_KEY not set (product id=%s).",
            product_id,
        )
    except Exception:
        logger.exception(
            "Gemini Líder product info failed for product id=%s",
            product_id,
        )
    return None


def _apply_lider_product_info(
    product: Product,
    info: LiderProductInfo,
    *,
    anchor: str,
) -> None:
    """Write Gemini Líder fields onto *product*; *anchor* resolves empty display_name."""
    next_name = (info.display_name or anchor).strip() or product.name
    if (
        Product.objects.filter(name__iexact=next_name)
        .exclude(pk=product.pk)
        .exists()
    ):
        raise ProductNameConflict(_GEMINI_SUGGESTED_NAME_CONFLICT)
    product.brand = info.brand
    product.price = info.price
    product.format = info.format
    product.standard_name = info.standard_name
    product.emoji = info.emoji
    product.name = next_name
    product.save(
        update_fields=[
            "brand",
            "price",
            "format",
            "standard_name",
            "emoji",
            "name",
        ],
    )


def find_products(*, query: str) -> list[LiderProductInfo]:
    """Return up to 10 Gemini Líder product rows for *query*; no DB writes."""
    normalized = query.strip()
    if not normalized:
        msg = "Product name must not be empty."
        raise ValueError(msg)
    try:
        return gemini_service.fetch_lider_product_candidates(query=normalized)
    except RuntimeError:
        logger.warning(
            "Skipped Gemini find products: GEMINI_API_KEY not set.",
        )
    except Exception:
        logger.exception(
            "Gemini find products failed for query=%r",
            normalized,
        )
    return []


def create_product_from_lider_info(*, query_name: str, info: LiderProductInfo) -> int:
    """Persist product using *info* from a prior find (no Gemini call). Raises ProductNameConflict."""
    anchor = query_name.strip()
    if not anchor:
        msg = "Product name must not be empty."
        raise ValueError(msg)
    next_name = (info.display_name or "").strip() or anchor
    if Product.objects.filter(name__iexact=next_name).exists():
        raise ProductNameConflict()
    try:
        product = Product.objects.create(
            name=next_name,
            original_name=anchor,
            standard_name=info.standard_name,
            brand=info.brand,
            price=info.price,
            format=info.format,
            emoji=info.emoji,
        )
    except IntegrityError as exc:
        raise ProductNameConflict() from exc
    return product.pk


def create_product(*, name: str) -> int:
    normalized = name.strip()
    if not normalized:
        msg = "Product name must not be empty."
        raise ValueError(msg)
    if Product.objects.filter(name__iexact=normalized).exists():
        raise ProductNameConflict()
    try:
        product = Product.objects.create(name=normalized, original_name=normalized)
    except IntegrityError as exc:
        raise ProductNameConflict() from exc

    info = _fetch_lider_product_info_or_none(
        product_name=normalized,
        product_id=product.pk,
    )
    if info:
        _apply_lider_product_info(product, info, anchor=normalized)

    return product.pk


def _anchor_name_for_gemini(product: Product) -> str:
    s = (product.original_name or "").strip()
    return s or product.name


def recheck_product_from_gemini(*, product_id: int) -> Product:
    """Reload Líder-oriented fields from Gemini for existing product. Raises Product.DoesNotExist."""
    product = Product.objects.get(pk=product_id)
    anchor = _anchor_name_for_gemini(product)
    info = _fetch_lider_product_info_or_none(product_name=anchor, product_id=product.pk)
    if info:
        _apply_lider_product_info(product, info, anchor=anchor)
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


def list_products(
    *,
    limit: int = DEFAULT_LIST_LIMIT,
    cursor: str | None = None,
    search: str | None = None,
) -> tuple[list[Product], str | None]:
    """List products with cursor pagination; optional case-insensitive substring search (ILIKE)."""
    lim = _clamp_limit(limit)
    q = (search or "").strip()

    qs = Product.objects.all().order_by("name", "pk")
    if q:
        qs = qs.filter(name__icontains=q)

    if cursor:
        payload = _decode_cursor(cursor)
        try:
            cq = payload["q"]
            cname = payload["n"]
            cpk = int(payload["i"])
        except (KeyError, TypeError, ValueError) as exc:
            raise InvalidProductListCursorError() from exc
        if cq != q:
            raise InvalidProductListCursorError("Cursor does not match request parameters.")
        qs = qs.filter(Q(name__gt=cname) | Q(name=cname, pk__gt=cpk))

    rows = list(qs[: lim + 1])
    has_more = len(rows) > lim
    page = rows[:lim]

    next_cursor = None
    if has_more and page:
        last = page[-1]
        next_cursor = _encode_cursor({"q": q, "n": last.name, "i": last.pk})
    return page, next_cursor


def add_product_to_basket(*, product_id: int, user_id: int) -> Basket:
    """Use latest open basket for *user_id*, or create one; append product."""
    product = Product.objects.get(pk=product_id)
    with transaction.atomic():
        basket = (
            Basket.objects.select_for_update()
            .filter(owner_id=user_id, purchased_at__isnull=True)
            .order_by("-created_at")
            .first()
        )
        if basket is None:
            basket = Basket.objects.create(owner_id=user_id)
        basket.products.add(product)
    return basket


def delete_product_from_basket(*, product_id: int, user_id: int) -> None:
    """Remove product from user's latest open basket. No-op if not in basket."""
    product = Product.objects.get(pk=product_id)
    with transaction.atomic():
        basket = (
            Basket.objects.select_for_update()
            .filter(owner_id=user_id, purchased_at__isnull=True)
            .order_by("-created_at")
            .first()
        )
        if basket is None:
            raise NoOpenBasketError()
        basket.products.remove(product)


def get_latest_basket_with_products(*, user_id: int) -> Basket | None:
    """Latest basket for *user* by created_at (any purchase state)."""
    return (
        Basket.objects.filter(owner_id=user_id)
        .prefetch_related(
            Prefetch("products", queryset=Product.objects.order_by("name", "pk")),
        )
        .order_by("-created_at")
        .first()
    )


def basket_total_price(*, basket: Basket) -> Decimal:
    """Sum of ``Product.price`` for lines in *basket*.

    Uses in-memory sum over ``basket.products.all()`` — pair with
    :func:`get_latest_basket_with_products` (prefetch) to avoid extra queries.
    """
    total = Decimal("0")
    for p in basket.products.all():
        total += p.price
    return total


def purchase_latest_open_basket(*, user_id: int) -> Basket:
    """Set purchased_at on user's latest open basket."""
    with transaction.atomic():
        basket = (
            Basket.objects.select_for_update()
            .filter(owner_id=user_id, purchased_at__isnull=True)
            .order_by("-created_at")
            .first()
        )
        if basket is None:
            raise NoOpenBasketError()
        basket.purchased_at = timezone.now()
        basket.save(update_fields=["purchased_at"])
    return basket
