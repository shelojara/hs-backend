"""Fetch page HTML and reduce to plain text for Gemini product extraction."""

from __future__ import annotations

import logging
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from groceries.favicon_service import USER_AGENT, normalize_website_url

logger = logging.getLogger(__name__)

_MAX_RESPONSE_BYTES = 1_500_000
_MAX_TEXT_CHARS = 24_000
_FETCH_TIMEOUT_S = 20.0


def is_http_https_url(s: str) -> bool:
    """True when *s* looks like http(s) URL with real host (not bare word like ``milk``)."""
    raw = (s or "").strip()
    if not raw:
        return False
    if not raw.startswith(("http://", "https://")):
        raw = f"https://{raw}"
    try:
        p = urlparse(raw)
    except ValueError:
        return False
    if p.scheme not in ("http", "https") or not p.netloc:
        return False
    host = p.hostname
    if not host:
        return False
    if host == "localhost":
        return True
    if "." in host:
        return True
    if ":" in host:
        return True
    return False


def normalize_fetch_url(s: str) -> str:
    """Strip and ensure http(s) scheme for fetching."""
    return normalize_website_url(s.strip())


def html_to_plain_text(html: str) -> str:
    """Drop script/style; body text with newlines (no cross-app import)."""
    soup = BeautifulSoup(html, "html.parser")
    root = soup.body or soup
    for tag in root.find_all(["script", "style"]):
        tag.decompose()
    return root.get_text(separator="\n", strip=True)


def fetch_page_text_for_product_context(url: str) -> str | None:
    """GET *url*, return truncated plain text or None on failure / empty."""
    fetch_url = normalize_fetch_url(url)
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8"}
    try:
        with httpx.Client(
            timeout=_FETCH_TIMEOUT_S,
            follow_redirects=True,
            headers=headers,
        ) as client:
            r = client.get(fetch_url)
            r.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("Product URL fetch failed url=%r: %s", fetch_url, exc)
        return None
    content = r.content
    if len(content) > _MAX_RESPONSE_BYTES:
        content = content[:_MAX_RESPONSE_BYTES]
    charset = r.encoding or "utf-8"
    try:
        html = content.decode(charset, errors="replace")
    except LookupError:
        html = content.decode("utf-8", errors="replace")
    text = html_to_plain_text(html)
    text = " ".join(text.split())
    if not text:
        return None
    if len(text) > _MAX_TEXT_CHARS:
        text = text[: _MAX_TEXT_CHARS - 3].rstrip() + "..."
    return text
