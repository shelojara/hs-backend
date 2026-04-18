import base64
import json
from dataclasses import dataclass
from typing import Any

from django.db import IntegrityError
from django.db.models import Q
from rapidfuzz import fuzz

from groceries.models import Product


class ProductNameConflict(Exception):
    """Another product already uses this name (case-insensitive)."""

    def __init__(self, message: str = "A product with this name already exists.") -> None:
        super().__init__(message)


class InvalidProductListCursorError(Exception):
    """Cursor token invalid or used with wrong parameters."""

    def __init__(self, message: str = "Invalid cursor.") -> None:
        super().__init__(message)


DEFAULT_LIST_LIMIT = 20
MAX_LIST_LIMIT = 100
DEFAULT_MIN_SIMILARITY = 60
_SCORE_SCALE = 10_000


def create_product(*, name: str) -> int:
    normalized = name.strip()
    if not normalized:
        msg = "Product name must not be empty."
        raise ValueError(msg)
    if Product.objects.filter(name__iexact=normalized).exists():
        raise ProductNameConflict()
    try:
        product = Product.objects.create(name=normalized)
    except IntegrityError as exc:
        raise ProductNameConflict() from exc
    return product.pk


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


@dataclass(frozen=True)
class ProductListItem:
    product_id: int
    name: str
    similarity_score: float | None = None


def _clamp_limit(limit: int) -> int:
    if limit < 1:
        return 1
    return min(limit, MAX_LIST_LIMIT)


def _score_name(query: str, name: str) -> float:
    q = query.strip()
    if not q:
        return 0.0
    pr = float(fuzz.partial_ratio(q, name))
    ts = float(fuzz.token_sort_ratio(q, name))
    return max(pr, ts)


def list_products(
    *,
    limit: int = DEFAULT_LIST_LIMIT,
    cursor: str | None = None,
    search: str | None = None,
    min_similarity: int = DEFAULT_MIN_SIMILARITY,
) -> tuple[list[ProductListItem], str | None]:
    """List products with cursor pagination; optional fuzzy search ranked by similarity."""
    lim = _clamp_limit(limit)
    q = (search or "").strip()
    ms = max(0, min(100, min_similarity))

    if not q:
        return _list_products_by_name(lim, cursor)

    return _list_products_by_similarity(lim, cursor, q, ms)


def _list_products_by_name(limit: int, cursor: str | None) -> tuple[list[ProductListItem], str | None]:
    qs = Product.objects.all().order_by("name", "pk")
    if cursor:
        payload = _decode_cursor(cursor)
        if payload.get("m") != "name":
            raise InvalidProductListCursorError("Cursor does not match listing mode.")
        try:
            cname = payload["n"]
            cpk = int(payload["i"])
        except (KeyError, TypeError, ValueError) as exc:
            raise InvalidProductListCursorError() from exc
        if payload.get("q", "") != "" or payload.get("ms") is not None:
            raise InvalidProductListCursorError("Cursor does not match request parameters.")
        qs = qs.filter(Q(name__gt=cname) | Q(name=cname, pk__gt=cpk))

    rows = list(qs[: limit + 1])
    has_more = len(rows) > limit
    page = rows[:limit]
    items = [ProductListItem(product_id=p.pk, name=p.name) for p in page]

    next_cursor = None
    if has_more and page:
        last = page[-1]
        next_cursor = _encode_cursor({"m": "name", "q": "", "n": last.name, "i": last.pk})
    return items, next_cursor


def _list_products_by_similarity(
    limit: int,
    cursor: str | None,
    query: str,
    min_similarity: int,
) -> tuple[list[ProductListItem], str | None]:
    scored: list[tuple[float, str, int]] = []
    for pk, name in Product.objects.values_list("pk", "name"):
        score = _score_name(query, name)
        if score >= min_similarity:
            scored.append((score, name, pk))

    scored.sort(key=lambda t: (-t[0], t[1], t[2]))

    start = 0
    if cursor:
        payload = _decode_cursor(cursor)
        if payload.get("m") != "search":
            raise InvalidProductListCursorError("Cursor does not match listing mode.")
        try:
            c_sc = int(payload["s"])
            cname = payload["n"]
            cpk = int(payload["i"])
        except (KeyError, TypeError, ValueError) as exc:
            raise InvalidProductListCursorError() from exc
        if payload.get("q") != query or int(payload.get("ms", min_similarity)) != min_similarity:
            raise InvalidProductListCursorError("Cursor does not match request parameters.")
        c_score = c_sc / _SCORE_SCALE
        start = _find_search_start_index(scored, c_score, cname, cpk)
        if start < 0:
            start = len(scored)

    slice_rows = scored[start : start + limit + 1]
    has_more = len(slice_rows) > limit
    page = slice_rows[:limit]

    items = [
        ProductListItem(
            product_id=pk,
            name=name,
            similarity_score=round(score, 2),
        )
        for score, name, pk in page
    ]

    next_cursor = None
    if has_more and page:
        score, name, pk = page[-1]
        next_cursor = _encode_cursor(
            {
                "m": "search",
                "q": query,
                "ms": min_similarity,
                "s": int(round(score * _SCORE_SCALE)),
                "n": name,
                "i": pk,
            }
        )
    return items, next_cursor


def _find_search_start_index(
    scored: list[tuple[float, str, int]],
    c_score: float,
    cname: str,
    cpk: int,
) -> int:
    # scored ordered like sort key (-score, name, pk); find first row strictly after cursor
    key_cursor = (-c_score, cname, cpk)
    for i, (score, name, pk) in enumerate(scored):
        key_row = (-score, name, pk)
        if key_row > key_cursor:
            return i
    return -1
