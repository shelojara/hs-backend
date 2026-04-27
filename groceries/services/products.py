import base64
import json
import logging
import unicodedata
from datetime import timedelta
from dataclasses import dataclass
from decimal import Decimal
from collections.abc import Callable
from typing import Any, TypeAlias

from django.db import transaction
from django.db.models import Q, QuerySet
from django.utils import timezone
from rapidfuzz import fuzz

from . import gemini as gemini_service
from .gemini import MerchantProductInfo
from groceries.models import Product
from groceries.schemas import ProductCandidateSchema

from .baskets import get_current_basket
from .constants import DEFAULT_LIST_LIMIT, MAX_LIST_LIMIT
from .exceptions import InvalidProductListCursorError
from .merchants import preferred_merchant_context_for_user

logger = logging.getLogger(__name__)

CatalogInCatalogCheck: TypeAlias = Callable[[str, str, str], bool]


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
            preferred_merchants=preferred_merchant_context_for_user(user_id),
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


def create_product_from_candidate(
    *,
    candidate: ProductCandidateSchema,
    user_id: int,
    is_custom: bool = False,
) -> int:
    """Persist product from merchant candidate fields.

    Custom products with blank emoji may call Gemini for a suggested emoji.
    """
    emoji = (candidate.emoji or "").strip()
    if is_custom and not emoji:
        try:
            emoji = gemini_service.suggest_product_emoji(
                name=candidate.name,
                standard_name=candidate.standard_name,
                brand=candidate.brand,
                format=candidate.format,
            )
        except RuntimeError:
            logger.warning(
                "Skipped Gemini product emoji: GEMINI_API_KEY not set (custom product name=%r).",
                candidate.name[:80],
            )
        except Exception:
            logger.exception(
                "Gemini product emoji failed for custom product name=%r",
                candidate.name[:80],
            )
    product = Product.objects.create(
        name=candidate.name,
        standard_name=candidate.standard_name,
        brand=(candidate.brand or "").strip(),
        price=candidate.price,
        format=candidate.format,
        emoji=emoji,
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
    quantity: int,
    emoji: str,
) -> Product:
    """Update persisted merchant fields.

    Blank emoji may call Gemini for a suggested emoji.
    """
    product = Product.objects.get(pk=product_id, user_id=user_id)
    br = (brand or "").strip()
    em = (emoji or "").strip()
    if not em:
        try:
            em = gemini_service.suggest_product_emoji(
                name=product.name,
                standard_name=standard_name,
                brand=br,
                format=format,
            )
        except RuntimeError:
            logger.warning(
                "Skipped Gemini product emoji: GEMINI_API_KEY not set (update product id=%s).",
                product_id,
            )
        except Exception:
            logger.exception(
                "Gemini product emoji failed on update for product id=%s",
                product_id,
            )
    product.standard_name = standard_name
    product.brand = br
    product.format = format
    product.price = price
    product.quantity = quantity
    product.emoji = em
    product.save(
        update_fields=["standard_name", "brand", "format", "price", "quantity", "emoji"],
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
    """Refresh *price* from Gemini using identity fields (standard_name or custom *name*).

    Does not change name, brand, format, emoji, or standard_name.

    Raises Product.DoesNotExist when no row matches *product_id* and *user_id*.
    Raises ValueError when identity text blank: non-custom needs *standard_name*;
    custom products may use *name* when *standard_name* empty.
    """
    product = Product.objects.get(pk=product_id, user_id=user_id)
    sn = (product.standard_name or "").strip()
    if not sn and product.is_custom:
        sn = (product.name or "").strip()
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


_LIST_PRODUCTS_CURSOR_QUERY = "q"
_LIST_PRODUCTS_CURSOR_RUNNING_LOW = "r"
_LIST_PRODUCTS_CURSOR_PURCHASE_COUNT = "c"
_LIST_PRODUCTS_CURSOR_NAME = "n"
_LIST_PRODUCTS_CURSOR_PRODUCT_ID = "i"
_LIST_PRODUCTS_CURSOR_USER_ID = "u"


def _parse_list_products_cursor_payload(
    cursor_payload: dict[str, Any],
    *,
    expected_search_query: str,
    expected_user_id: int,
) -> tuple[bool, int, str, int]:
    """Return (running_low, purchase_count, product_name, product_id) after validating query and user."""
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
    running_low = bool(cursor_payload.get(_LIST_PRODUCTS_CURSOR_RUNNING_LOW))
    return running_low, purchase_count, product_name, product_id


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


_MIN_PRODUCT_SEARCH_WEIGHTED_RATIO = 65


def load_user_catalog_standard_names_normalized(*, user_id: int) -> frozenset[str]:
    """Normalized ``standard_name`` values (non-blank after strip) for search candidate ``in_catalog``."""
    out: set[str] = set()
    for std in Product.objects.filter(user_id=user_id).values_list(
        "standard_name",
        flat=True,
    ).iterator(chunk_size=500):
        s = str(std or "").strip()
        if not s:
            continue
        if (n := _normalize_for_product_search(s)):
            out.add(n)
    return frozenset(out)


def candidate_in_user_catalog_by_standard_name(
    *,
    name: str,
    standard_name: str,
    brand: str,
    catalog_standard_names: frozenset[str],
) -> bool:
    """True when candidate ``standard_name`` or display ``name`` equals some catalog ``standard_name`` (folded)."""
    _ = brand
    for raw in (standard_name.strip(), name.strip()):
        if not raw:
            continue
        if (n := _normalize_for_product_search(raw)) and n in catalog_standard_names:
            return True
    return False


def make_user_catalog_in_catalog_check(*, user_id: int) -> CatalogInCatalogCheck:
    """Single catalog load; same rule as *GetSearch* / *ListSearches* ``in_catalog``."""
    catalog_standard_names = load_user_catalog_standard_names_normalized(user_id=user_id)

    def check(name: str, standard_name: str, brand: str) -> bool:
        return candidate_in_user_catalog_by_standard_name(
            name=name,
            standard_name=standard_name,
            brand=brand,
            catalog_standard_names=catalog_standard_names,
        )

    return check


def recipe_ingredient_in_catalog_flags(
    *, user_id: int, ingredient_names: list[str]
) -> dict[str, bool]:
    """Per stripped *ingredient_names* key: any active catalog product has ``standard_name`` containing that string (case-insensitive)."""
    out: dict[str, bool] = {}
    for raw in ingredient_names:
        n = (raw or "").strip()
        if n in out:
            continue
        if not n:
            out[n] = False
            continue
        out[n] = Product.objects.filter(
            user_id=user_id,
            standard_name__icontains=n,
        ).exists()
    return out


@dataclass(frozen=True, slots=True)
class _ProductFuzzySearchRank:
    """Sort descending on ratio fields, running_low, purchase count; ascending on name and id."""

    product: Product
    weighted_ratio: int
    partial_ratio_score: int
    ratio_score: int

    def sort_tuple(self) -> tuple[int, int, int, int, int, int, str, int]:
        return (
            -self.weighted_ratio,
            -self.partial_ratio_score,
            -self.ratio_score,
            -int(self.product.running_low),
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
        (
            cursor_running_low,
            cursor_purchase_count,
            cursor_product_name,
            cursor_product_id,
        ) = _parse_list_products_cursor_payload(
            cursor_payload,
            expected_search_query=search_query,
            expected_user_id=user_id,
        )
        for index, product in enumerate(products_sorted_by_score):
            if (
                bool(product.running_low) == cursor_running_low
                and product.purchase_count == cursor_purchase_count
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
                _LIST_PRODUCTS_CURSOR_RUNNING_LOW: last_product.running_low,
                _LIST_PRODUCTS_CURSOR_PURCHASE_COUNT: last_product.purchase_count,
                _LIST_PRODUCTS_CURSOR_NAME: last_product.name,
                _LIST_PRODUCTS_CURSOR_PRODUCT_ID: last_product.pk,
                _LIST_PRODUCTS_CURSOR_USER_ID: user_id,
            }
        )
    return page_products, next_cursor


def list_products(
    *,
    user_id: int,
    limit: int = DEFAULT_LIST_LIMIT,
    cursor: str | None = None,
    search: str | None = None,
) -> tuple[list[Product], str | None]:
    """List products with cursor pagination; optional in-memory RapidFuzz search.

    Non-search: DB pagination, ``user_id`` scoped, same ordering.

    Order: ``running_low`` descending (flagged first), then ``purchase_count`` descending,
    then ``name`` and ``pk`` ascending.

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
        "-running_low",
        "-purchase_count",
        "name",
        "pk",
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
        (
            cursor_running_low,
            cursor_purchase_count,
            cursor_product_name,
            cursor_product_id,
        ) = _parse_list_products_cursor_payload(
            cursor_payload,
            expected_search_query=trimmed_search_query,
            expected_user_id=user_id,
        )
        filtered_queryset = filtered_queryset.filter(
            Q(running_low__lt=cursor_running_low)
            | Q(
                running_low=cursor_running_low,
                purchase_count__lt=cursor_purchase_count,
            )
            | Q(
                running_low=cursor_running_low,
                purchase_count=cursor_purchase_count,
                name__gt=cursor_product_name,
            )
            | Q(
                running_low=cursor_running_low,
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
                _LIST_PRODUCTS_CURSOR_RUNNING_LOW: last_product.running_low,
                _LIST_PRODUCTS_CURSOR_PURCHASE_COUNT: last_product.purchase_count,
                _LIST_PRODUCTS_CURSOR_NAME: last_product.name,
                _LIST_PRODUCTS_CURSOR_PRODUCT_ID: last_product.pk,
                _LIST_PRODUCTS_CURSOR_USER_ID: user_id,
            }
        )
    return page_products, next_cursor


def mark_product_not_running_low(*, product_id: int, user_id: int) -> Product:
    """Clear ``running_low`` and snooze automated re-flagging for :data:`RUNNING_LOW_MANUAL_SNOOZE_DAYS`."""
    from .constants import RUNNING_LOW_MANUAL_SNOOZE_DAYS

    product = Product.objects.get(pk=product_id, user_id=user_id)
    until = timezone.now() + timedelta(days=RUNNING_LOW_MANUAL_SNOOZE_DAYS)
    product.running_low = False
    product.running_low_snoozed_until = until
    product.save(update_fields=["running_low", "running_low_snoozed_until"])
    return product


def running_low_sync_user_ids() -> list[int]:
    """Distinct user ids that own at least one active (non-soft-deleted) product."""
    return list(
        Product.objects.order_by()
        .values_list("user_id", flat=True)
        .distinct(),
    )
