"""Merchants and favicon / website URL helpers used by merchants and URL fetch."""

from __future__ import annotations

import logging
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from django.db.models import Max

from .gemini import PreferredMerchantContext
from groceries.models import Merchant

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (compatible; GroceriesBot/1.0; +https://example.com) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def normalize_website_url(website: str) -> str:
    """Strip *website* and ensure an http(s) scheme for storage and fetching."""
    s = website.strip()
    if not s:
        msg = "Website URL must not be empty."
        raise ValueError(msg)
    if not s.startswith(("http://", "https://")):
        s = f"https://{s}"
    return s


def _google_favicon_fallback(netloc: str) -> str:
    return f"https://www.google.com/s2/favicons?domain={netloc}&sz=64"


def fetch_favicon_url(website: str) -> str | None:
    """
    Best-effort favicon URL for *website*.

    Tries: <link rel="icon"> (and variants), then /favicon.ico, then Google's favicon service.
    Returns None only if the site URL cannot be parsed at all.
    """
    try:
        base = normalize_website_url(website)
    except ValueError:
        return None

    parsed = urlparse(base)
    if not parsed.netloc:
        return None

    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml,*/*"}

    try:
        with httpx.Client(timeout=12.0, follow_redirects=True, headers=headers) as client:
            try:
                response = client.get(base)
                response.raise_for_status()
            except httpx.HTTPError:
                logger.info("Could not fetch page for favicon: %s", base)
                return _google_favicon_fallback(parsed.netloc)

            ctype = (response.headers.get("content-type") or "").lower()
            if "html" not in ctype and "xml" not in ctype:
                return _google_favicon_fallback(parsed.netloc)

            soup = BeautifulSoup(response.text, "html.parser")
            for link in soup.find_all("link"):
                rel = link.get("rel")
                if rel is None:
                    continue
                rel_str = (
                    " ".join(rel)
                    if isinstance(rel, (list, tuple))
                    else str(rel)
                ).lower()
                if "icon" not in rel_str:
                    continue
                href = link.get("href")
                if not href or not str(href).strip():
                    continue
                absolute = urljoin(str(response.url), str(href).strip())
                return absolute

            ico_url = urljoin(str(response.url), "/favicon.ico")
            try:
                head = client.head(ico_url)
                if head.status_code == 200:
                    return str(head.url)
                get = client.get(ico_url)
                if get.status_code == 200 and get.content[:4] in (
                    b"\x00\x00\x01\x00",
                    b"GIF8",
                    b"\x89PNG",
                    b"RIFF",
                ):
                    return str(get.url)
            except httpx.HTTPError:
                pass

            return _google_favicon_fallback(parsed.netloc)
    except Exception:
        logger.exception("Unexpected error resolving favicon for %s", base)
        return _google_favicon_fallback(parsed.netloc)


def preferred_merchant_context_for_user(user_id: int) -> list[PreferredMerchantContext]:
    rows = Merchant.objects.filter(user_id=user_id).order_by(
        "preference_order",
        "pk",
    )
    return [
        PreferredMerchantContext(name=m.name, website=m.website)
        for m in rows
    ]


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
