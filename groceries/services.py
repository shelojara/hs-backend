import base64
import json
from dataclasses import dataclass
from typing import Any

from django.db import IntegrityError
from django.db.models import Q

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


def _clamp_limit(limit: int) -> int:
    if limit < 1:
        return 1
    return min(limit, MAX_LIST_LIMIT)


def list_products(
    *,
    limit: int = DEFAULT_LIST_LIMIT,
    cursor: str | None = None,
    search: str | None = None,
) -> tuple[list[ProductListItem], str | None]:
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
    items = [ProductListItem(product_id=p.pk, name=p.name) for p in page]

    next_cursor = None
    if has_more and page:
        last = page[-1]
        next_cursor = _encode_cursor({"q": q, "n": last.name, "i": last.pk})
    return items, next_cursor
