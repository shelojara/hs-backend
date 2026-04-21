"""In-memory fuzzy ranking for ``list_products`` search (RapidFuzz + accent fold)."""

import base64
import json
import unicodedata
from typing import Any

from django.db.models import QuerySet
from rapidfuzz import fuzz

from groceries.models import Product


class InvalidProductListCursorError(Exception):
    """Cursor token invalid or used with wrong parameters."""

    def __init__(self, message: str = "Invalid cursor.") -> None:
        super().__init__(message)


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def encode_product_list_cursor(payload: dict[str, Any]) -> str:
    return _b64url_encode(json.dumps(payload, separators=(",", ":")).encode())


def decode_product_list_cursor(token: str) -> dict[str, Any]:
    try:
        return json.loads(_b64url_decode(token).decode())
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise InvalidProductListCursorError() from exc


def _strip_accents(s: str) -> str:
    """ASCII-ish fold for search; NFD then drop combining marks."""
    return "".join(
        c
        for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn"
    )


def _normalize_for_product_search(s: str) -> str:
    return _strip_accents(s.casefold())


def _product_search_haystack(name: str, standard_name: str, brand: str) -> str:
    """Single folded string: *name*, *standard_name*, *brand* (non-blank, deduped order)."""
    parts: list[str] = []
    for part in (name.strip(), standard_name.strip(), brand.strip()):
        if part and part not in parts:
            parts.append(part)
    if not parts:
        return ""
    return _normalize_for_product_search(" ".join(parts))


# ``fuzz.WRatio`` below this → skip row (drops weak substring noise, e.g. ``xo`` vs ``hello``).
_MIN_PRODUCT_SEARCH_WRATIO = 65


def list_products_with_fuzzy_search(
    *,
    base_qs: QuerySet[Product],
    cart_pks: set[int],
    user_id: int,
    query: str,
    limit: int,
    cursor: str | None,
) -> tuple[list[Product], str | None]:
    """Score catalog in memory with RapidFuzz; cursor pagination over sorted hits."""
    q_norm = _normalize_for_product_search(query)
    scored: list[tuple[tuple[int, int, int, int, str, int], Product]] = []
    for p in base_qs.iterator(chunk_size=500):
        if p.pk in cart_pks:
            continue
        hay = _product_search_haystack(p.name, p.standard_name, p.brand)
        if not hay:
            continue
        wr = int(fuzz.WRatio(q_norm, hay))
        if wr < _MIN_PRODUCT_SEARCH_WRATIO:
            continue
        pr = int(fuzz.partial_ratio(q_norm, hay))
        r = int(fuzz.ratio(q_norm, hay))
        key = (-wr, -pr, -r, -p.purchase_count, p.name, p.pk)
        scored.append((key, p))
    scored.sort(key=lambda t: t[0])
    ordered = [t[1] for t in scored]

    start = 0
    if cursor:
        payload = decode_product_list_cursor(cursor)
        try:
            cq = payload["q"]
            c_count = int(payload["c"])
            cname = payload["n"]
            cpk = int(payload["i"])
            cu = payload.get("u")
        except (KeyError, TypeError, ValueError) as exc:
            raise InvalidProductListCursorError() from exc
        if cq != query:
            raise InvalidProductListCursorError(
                "Cursor does not match request parameters."
            )
        if cu != user_id:
            raise InvalidProductListCursorError(
                "Cursor does not match request parameters."
            )
        for i, row in enumerate(ordered):
            if (
                row.purchase_count == c_count
                and row.name == cname
                and row.pk == cpk
            ):
                start = i + 1
                break
        else:
            raise InvalidProductListCursorError()

    slice_rows = ordered[start : start + limit + 1]
    has_more = len(slice_rows) > limit
    page = slice_rows[:limit]
    next_cursor = None
    if has_more and page:
        last = page[-1]
        next_cursor = encode_product_list_cursor(
            {
                "q": query,
                "c": last.purchase_count,
                "n": last.name,
                "i": last.pk,
                "u": user_id,
            }
        )
    return page, next_cursor
