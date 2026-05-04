"""HTTP client for MangaBaka public API (https://api.mangabaka.dev/v1/)."""

from __future__ import annotations

from typing import Any
from urllib.parse import urljoin

import httpx
from django.conf import settings


class MangaBakaAPIError(Exception):
    """Non-success response or unexpected payload from MangaBaka API."""


def _series_url(series_id: int) -> str:
    base = (getattr(settings, "MANGABAKA_API_BASE_URL", None) or "https://api.mangabaka.dev/v1/").rstrip("/") + "/"
    return urljoin(base, f"series/{series_id}")


def _search_url() -> str:
    base = (getattr(settings, "MANGABAKA_API_BASE_URL", None) or "https://api.mangabaka.dev/v1/").rstrip("/") + "/"
    return urljoin(base, "series/search")


def fetch_series_detail(*, series_id: int, timeout: float = 30.0) -> dict[str, Any]:
    """GET /v1/series/{id}; returns ``data`` object (title, description, rating, …)."""
    url = _series_url(series_id)
    headers = {"User-Agent": getattr(settings, "MANGABAKA_HTTP_USER_AGENT", "hs-backend-manga/1.0")}
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.get(url, headers=headers)
            resp.raise_for_status()
            body = resp.json()
    except httpx.HTTPError as exc:
        raise MangaBakaAPIError(str(exc)) from exc
    if body.get("status") != 200:
        raise MangaBakaAPIError(str(body.get("message", body)))
    data = body.get("data")
    if not isinstance(data, dict):
        raise MangaBakaAPIError("missing or invalid data object")
    return data


def search_series(
    *,
    query: str,
    limit: int = 10,
    page: int = 1,
    timeout: float = 30.0,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """GET /v1/series/search; returns (data list, pagination dict or None)."""
    url = _search_url()
    headers = {"User-Agent": getattr(settings, "MANGABAKA_HTTP_USER_AGENT", "hs-backend-manga/1.0")}
    params: dict[str, Any] = {"q": query, "page": page, "limit": limit}
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.get(url, headers=headers, params=params)
            resp.raise_for_status()
            body = resp.json()
    except httpx.HTTPError as exc:
        raise MangaBakaAPIError(str(exc)) from exc
    if body.get("status") != 200:
        raise MangaBakaAPIError(str(body.get("message", body)))
    data = body.get("data")
    if not isinstance(data, list):
        raise MangaBakaAPIError("missing or invalid search data list")
    pag = body.get("pagination")
    pagination = pag if isinstance(pag, dict) else None
    return data, pagination
