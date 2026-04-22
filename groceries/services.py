import base64
import json
import logging
import unicodedata
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from dateutil.relativedelta import relativedelta

from django.db import transaction
from django.db.models import F, Max, Prefetch, Q, QuerySet
from django.utils import timezone
from django_q.tasks import async_task
from rapidfuzz import fuzz

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
        brand=(candidate.brand or "").strip(),
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
    product.brand = (brand or "").strip()
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


def _clamp_limit(limit: int) -> int:
    if limit < 1:
        return 1
    return min(limit, MAX_LIST_LIMIT)


def _encode_bytes_as_url_safe_base64_without_padding(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_url_safe_base64_without_padding_to_bytes(encoded: str) -> bytes:
    padding = "=" * (-len(encoded) % 4)
    return base64.urlsafe_b64decode(encoded + padding)


def _encode_list_products_cursor(payload: dict[str, Any]) -> str:
    return _encode_bytes_as_url_safe_base64_without_padding(
        json.dumps(payload, separators=(",", ":")).encode()
    )


def _decode_list_products_cursor(token: str) -> dict[str, Any]:
    try:
        raw_json = _decode_url_safe_base64_without_padding_to_bytes(token).decode()
        return json.loads(raw_json)
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise InvalidProductListCursorError() from exc


# Keys in persisted list-products cursor payloads (short keys keep tokens small).
_LIST_PRODUCTS_CURSOR_QUERY = "q"
_LIST_PRODUCTS_CURSOR_PURCHASE_COUNT = "c"
_LIST_PRODUCTS_CURSOR_NAME = "n"
_LIST_PRODUCTS_CURSOR_PRODUCT_ID = "i"
_LIST_PRODUCTS_CURSOR_USER_ID = "u"


def _parse_list_products_cursor_payload(
    cursor_payload: dict[str, Any],
    *,
    expected_search_query: str,
    expected_user_id: int,
) -> tuple[int, str, int]:
    """Return (purchase_count, product_name, product_id) after validating query and user."""
    try:
        cursor_query = cursor_payload[_LIST_PRODUCTS_CURSOR_QUERY]
        purchase_count = int(cursor_payload[_LIST_PRODUCTS_CURSOR_PURCHASE_COUNT])
        product_name = cursor_payload[_LIST_PRODUCTS_CURSOR_NAME]
        product_id = int(cursor_payload[_LIST_PRODUCTS_CURSOR_PRODUCT_ID])
        cursor_user_id = cursor_payload.get(_LIST_PRODUCTS_CURSOR_USER_ID)
    except (KeyError, TypeError, ValueError) as exc:
        raise InvalidProductListCursorError() from exc
    if cursor_query != expected_search_query:
        raise InvalidProductListCursorError(
            "Cursor does not match request parameters."
        )
    if cursor_user_id != expected_user_id:
        raise InvalidProductListCursorError(
            "Cursor does not match request parameters."
        )
    return purchase_count, product_name, product_id


def _strip_accents(text: str) -> str:
    """ASCII-ish fold for search; NFD then drop combining marks."""
    return "".join(
        character
        for character in unicodedata.normalize("NFD", text)
        if unicodedata.category(character) != "Mn"
    )


def _normalize_for_product_search(text: str) -> str:
    return _strip_accents(text.casefold())


def _product_search_haystack(name: str, standard_name: str, brand: str) -> str:
    """Single folded string: *name*, *standard_name*, *brand* (non-blank, deduped order)."""
    parts: list[str] = []
    for part in (name.strip(), standard_name.strip(), brand.strip()):
        if part and part not in parts:
            parts.append(part)
    if not parts:
        return ""
    return _normalize_for_product_search(" ".join(parts))


def _product_search_field_strings(name: str, standard_name: str, brand: str) -> list[str]:
    """Normalized non-blank fields (name, standard_name, brand), deduped order — for per-field fuzzy gate."""
    out: list[str] = []
    for raw in (name.strip(), standard_name.strip(), brand.strip()):
        if not raw:
            continue
        folded = _normalize_for_product_search(raw)
        if folded and folded not in out:
            out.append(folded)
    return out


def _field_fuzzy_gate_score(query_normalized: str, field_normalized: str) -> int:
    """0–100 match strength for *query* vs one product field.

    ``fuzz.WRatio`` on full field underrates substring matches when field is long; per-token
    ``fuzz.ratio`` fixes that. Combined with ``token_set_ratio`` on the field so multi-word
    queries still match (e.g. ``organic milk`` vs a long ``standard_name``).
    """
    if not field_normalized:
        return 0
    words = field_normalized.split()
    if not words:
        return int(fuzz.ratio(query_normalized, field_normalized))
    max_word_ratio = max(
        int(fuzz.ratio(query_normalized, word)) for word in words
    )
    token_set = int(fuzz.token_set_ratio(query_normalized, field_normalized))
    return max(max_word_ratio, token_set)


# Best per-field gate score below this → skip row.
_MIN_PRODUCT_SEARCH_WEIGHTED_RATIO = 65


@dataclass(frozen=True, slots=True)
class _ProductFuzzySearchRank:
    """Sort descending on ratio fields and purchase count; ascending on name and id for stability."""

    product: Product
    weighted_ratio: int
    partial_ratio_score: int
    ratio_score: int

    def sort_tuple(self) -> tuple[int, int, int, int, str, int]:
        return (
            -self.weighted_ratio,
            -self.partial_ratio_score,
            -self.ratio_score,
            -self.product.purchase_count,
            self.product.name,
            self.product.pk,
        )


def _list_products_with_fuzzy_search(
    *,
    product_queryset: QuerySet[Product],
    product_ids_in_open_basket: set[int],
    user_id: int,
    search_query: str,
    page_size: int,
    cursor_token: str | None,
) -> tuple[list[Product], str | None]:
    """Score catalog in memory with RapidFuzz; cursor pagination over sorted hits."""
    query_normalized = _normalize_for_product_search(search_query)
    ranked_rows: list[_ProductFuzzySearchRank] = []
    for product in product_queryset.iterator(chunk_size=500):
        if product.pk in product_ids_in_open_basket:
            continue
        haystack_normalized = _product_search_haystack(
            product.name, product.standard_name, product.brand
        )
        if not haystack_normalized:
            continue
        field_strings = _product_search_field_strings(
            product.name, product.standard_name, product.brand
        )
        weighted_ratio = max(
            _field_fuzzy_gate_score(query_normalized, field_text)
            for field_text in field_strings
        )
        if weighted_ratio < _MIN_PRODUCT_SEARCH_WEIGHTED_RATIO:
            continue
        partial_ratio_score = int(
            fuzz.partial_ratio(query_normalized, haystack_normalized)
        )
        ratio_score = int(fuzz.ratio(query_normalized, haystack_normalized))
        ranked_rows.append(
            _ProductFuzzySearchRank(
                product=product,
                weighted_ratio=weighted_ratio,
                partial_ratio_score=partial_ratio_score,
                ratio_score=ratio_score,
            )
        )
    ranked_rows.sort(key=lambda row: row.sort_tuple())
    products_sorted_by_score = [row.product for row in ranked_rows]

    slice_start_index = 0
    if cursor_token is not None:
        cursor_payload = _decode_list_products_cursor(cursor_token)
        cursor_purchase_count, cursor_product_name, cursor_product_id = (
            _parse_list_products_cursor_payload(
                cursor_payload,
                expected_search_query=search_query,
                expected_user_id=user_id,
            )
        )
        for index, product in enumerate(products_sorted_by_score):
            if (
                product.purchase_count == cursor_purchase_count
                and product.name == cursor_product_name
                and product.pk == cursor_product_id
            ):
                slice_start_index = index + 1
                break
        else:
            raise InvalidProductListCursorError()

    slice_upper_bound = slice_start_index + page_size + 1
    page_slice = products_sorted_by_score[slice_start_index:slice_upper_bound]
    has_next_page = len(page_slice) > page_size
    page_products = page_slice[:page_size]
    next_cursor = None
    if has_next_page and page_products:
        last_product = page_products[-1]
        next_cursor = _encode_list_products_cursor(
            {
                _LIST_PRODUCTS_CURSOR_QUERY: search_query,
                _LIST_PRODUCTS_CURSOR_PURCHASE_COUNT: last_product.purchase_count,
                _LIST_PRODUCTS_CURSOR_NAME: last_product.name,
                _LIST_PRODUCTS_CURSOR_PRODUCT_ID: last_product.pk,
                _LIST_PRODUCTS_CURSOR_USER_ID: user_id,
            }
        )
    return page_products, next_cursor


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
    """List products with cursor pagination; optional in-memory RapidFuzz search.

    Non-search: DB pagination, ``user_id`` scoped, same ordering.

    Excludes products already in *user_id*'s current open basket (same basket as add/remove).
    """
    page_size = _clamp_limit(limit)
    trimmed_search_query = (search or "").strip()

    basket = get_current_basket(user_id=user_id)
    product_ids_in_open_basket: set[int] = set()
    if basket is not None:
        product_ids_in_open_basket = set(
            basket.products.values_list("pk", flat=True)
        )

    user_product_queryset = Product.objects.filter(user_id=user_id).order_by(
        "-purchase_count", "name", "pk"
    )

    if trimmed_search_query:
        return _list_products_with_fuzzy_search(
            product_queryset=user_product_queryset,
            product_ids_in_open_basket=product_ids_in_open_basket,
            user_id=user_id,
            search_query=trimmed_search_query,
            page_size=page_size,
            cursor_token=cursor,
        )

    filtered_queryset = user_product_queryset
    if product_ids_in_open_basket:
        filtered_queryset = filtered_queryset.exclude(
            pk__in=product_ids_in_open_basket
        )

    if cursor:
        cursor_payload = _decode_list_products_cursor(cursor)
        cursor_purchase_count, cursor_product_name, cursor_product_id = (
            _parse_list_products_cursor_payload(
                cursor_payload,
                expected_search_query=trimmed_search_query,
                expected_user_id=user_id,
            )
        )
        filtered_queryset = filtered_queryset.filter(
            Q(purchase_count__lt=cursor_purchase_count)
            | Q(
                purchase_count=cursor_purchase_count,
                name__gt=cursor_product_name,
            )
            | Q(
                purchase_count=cursor_purchase_count,
                name=cursor_product_name,
                pk__gt=cursor_product_id,
            )
        )

    rows = list(filtered_queryset[: page_size + 1])
    has_next_page = len(rows) > page_size
    page_products = rows[:page_size]

    next_cursor = None
    if has_next_page and page_products:
        last_product = page_products[-1]
        next_cursor = _encode_list_products_cursor(
            {
                _LIST_PRODUCTS_CURSOR_QUERY: trimmed_search_query,
                _LIST_PRODUCTS_CURSOR_PURCHASE_COUNT: last_product.purchase_count,
                _LIST_PRODUCTS_CURSOR_NAME: last_product.name,
                _LIST_PRODUCTS_CURSOR_PRODUCT_ID: last_product.pk,
                _LIST_PRODUCTS_CURSOR_USER_ID: user_id,
            }
        )
    return page_products, next_cursor


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


def _search_candidate_dict(p: MerchantProductInfo) -> dict[str, Any]:
    """JSON-serializable dict for ``Search.result_candidates``."""
    price_out: str | None = None
    if p.price is not None:
        price_out = str(p.price.quantize(Decimal("0.01")))
    return {
        "display_name": p.display_name,
        "standard_name": p.standard_name,
        "brand": p.brand,
        "price": price_out,
        "format": p.format,
        "emoji": p.emoji,
        "merchant": p.merchant,
    }


def _search_candidates_as_json(items: list[MerchantProductInfo]) -> list[dict[str, Any]]:
    return [_search_candidate_dict(p) for p in items]


def create_search(*, query: str, user_id: int) -> int:
    """Create pending ``Search`` and enqueue Gemini worker; returns primary key."""
    normalized = query.strip()
    if not normalized:
        msg = "Query must not be empty."
        raise ValueError(msg)
    row = Search.objects.create(user_id=user_id, query=normalized)
    async_task(
        "groceries.scheduled_tasks.run_product_search_job",
        row.pk,
        task_name=f"groceries_product_search:{row.pk}",
    )
    return row.pk


def list_searches(*, user_id: int) -> list[Search]:
    """Latest 10 ``Search`` rows for *user_id*, newest first (by primary key)."""
    return list(Search.objects.filter(user_id=user_id).order_by("-created_at", "-pk")[:10])


def get_search(search_id: int, *, user_id: int) -> Search:
    """Return one ``Search`` row owned by *user_id*."""
    return Search.objects.get(pk=search_id, user_id=user_id)


def delete_search(*, search_id: int, user_id: int) -> None:
    """Soft-delete ``Search`` row owned by *user_id*."""
    row = Search.objects.get(pk=search_id, user_id=user_id)
    now = timezone.now()
    row.deleted_at = now
    row.save(update_fields=["deleted_at"])


def search_result_candidates_as_product_schemas(
    raw: list[Any],
    *,
    fallback_name: str,
) -> list[ProductCandidateSchema]:
    """Map persisted ``Search.result_candidates`` JSON to ``ProductCandidateSchema`` rows."""
    q = (fallback_name or "").strip()
    out: list[ProductCandidateSchema] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        d: dict[str, Any] = item
        disp = str(d.get("display_name") or d.get("name") or "").strip()
        label = disp if disp else q
        std = str(d.get("standard_name") or "").strip()
        brand = str(d.get("brand") or "").strip()
        fmt = str(d.get("format") or "").strip()
        emoji = str(d.get("emoji") or "").strip()
        merchant = str(d.get("merchant") or "").strip()
        price_out: Decimal | None = None
        pr = d.get("price")
        if pr is not None and pr != "":
            try:
                price_out = Decimal(str(pr))
            except (ArithmeticError, ValueError, TypeError):
                price_out = None
        out.append(
            ProductCandidateSchema(
                name=label,
                standard_name=std,
                brand=brand,
                price=price_out,
                format=fmt,
                emoji=emoji,
                merchant=merchant,
            ),
        )
    return out


def run_product_search_job(*, search_id: int) -> None:
    """Background worker: Gemini product candidates → ``Search`` row."""
    try:
        search = Search.all_objects.get(pk=search_id)
    except Search.DoesNotExist:
        logger.warning("run_product_search_job: missing Search id=%s", search_id)
        return
    if search.deleted_at is not None:
        logger.warning(
            "run_product_search_job: Search id=%s soft-deleted; skipping.",
            search_id,
        )
        return
    user_id = search.user_id
    q = search.query.strip()
    kind_val = ""
    try:
        kind_val = gemini_service.classify_search_query_kind(query=q)
    except RuntimeError:
        logger.warning(
            "run_product_search_job: skip query kind (GEMINI unset) (search id=%s).",
            search_id,
        )
    except Exception:
        logger.exception(
            "run_product_search_job: classify query kind failed (search id=%s)",
            search_id,
        )
    search.kind = kind_val
    page_context: str | None = None
    if is_http_https_url(q):
        page_context = fetch_page_text_for_product_context(q)
    try:
        items = gemini_service.fetch_merchant_product_candidates(
            query=q,
            preferred_merchants=_preferred_merchant_context_for_user(user_id),
            page_context=page_context,
        )
        search.result_candidates = _search_candidates_as_json(items)
        search.status = SearchStatus.COMPLETED
        search.completed_at = timezone.now()
        search.save(
            update_fields=["kind", "result_candidates", "status", "completed_at"],
        )
    except RuntimeError:
        logger.warning(
            "run_product_search_job: GEMINI_API_KEY unset (search id=%s).",
            search_id,
        )
        search.status = SearchStatus.FAILED
        search.completed_at = timezone.now()
        search.save(update_fields=["kind", "status", "completed_at"])
    except Exception:
        logger.exception("run_product_search_job failed (search id=%s)", search_id)
        search.status = SearchStatus.FAILED
        search.completed_at = timezone.now()
        search.save(update_fields=["kind", "status", "completed_at"])
