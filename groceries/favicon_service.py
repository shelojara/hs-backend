"""Resolve a website's favicon URL (HTML link tags, /favicon.ico, or fallback)."""

from __future__ import annotations

import logging
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

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
