from urllib.parse import urljoin

from bs4 import BeautifulSoup
from bs4.element import Tag
from markdownify import markdownify

_CHROME_ROLE = frozenset({"navigation", "contentinfo"})

# id/class substrings → treat as nav or footer chrome (lowercased match)
_CHROME_ID_CLASS_MARKERS = (
    "navbar",
    "nav-bar",
    "nav_bar",
    "site-nav",
    "sitenav",
    "main-nav",
    "mainnav",
    "topnav",
    "top-nav",
    "bottom-nav",
    "bottomnav",
    "header-nav",
    "footernav",
    "footer-nav",
    "page-footer",
    "site-footer",
    "global-footer",
    "sticky-footer",
    "footer-wrapper",
    "footercontainer",
)


def _chrome_id_class_blob(tag: Tag) -> str:
    parts: list[str] = []
    tid = tag.get("id")
    if isinstance(tid, str):
        parts.append(tid)
    classes = tag.get("class")
    if isinstance(classes, list):
        parts.extend(str(c) for c in classes)
    elif isinstance(classes, str):
        parts.append(classes)
    return " ".join(parts).lower()


def _strip_nav_and_footer(body: Tag) -> None:
    """Remove nav bars and footers from body (semantic tags, roles, common id/class)."""
    for tag in body.find_all(["nav", "footer"]):
        tag.decompose()

    for tag in body.find_all(attrs={"role": True}):
        role = (tag.get("role") or "").strip().lower()
        if role in _CHROME_ROLE:
            tag.decompose()

    for tag in body.find_all(["div", "header", "aside", "section"]):
        blob = _chrome_id_class_blob(tag)
        if not blob:
            continue
        if any(m in blob for m in _CHROME_ID_CLASS_MARKERS):
            tag.decompose()


def extract_body_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    body = soup.body or soup

    for tag in body.find_all(["script", "style"]):
        tag.decompose()

    _strip_nav_and_footer(body)

    return body.get_text(separator="\n", strip=True)


def extract_body_html(html: str) -> str:
    """Return inner HTML of the document body (no head/doctype), scripts/styles removed."""
    soup = BeautifulSoup(html, "html.parser")
    body = soup.body or soup

    for tag in body.find_all(["script", "style"]):
        tag.decompose()

    _strip_nav_and_footer(body)

    return body.decode_contents()


def html_to_markdown(html: str) -> str:
    """Convert HTML fragment to Markdown (python-markdownify)."""
    fragment = html or ""
    if not fragment.strip():
        return ""
    return markdownify(fragment, heading_style="ATX").strip()


def extract_metadata(html: str, page_url: str) -> dict[str, str]:
    """Extract title and icon URL from page HTML."""
    soup = BeautifulSoup(html, "html.parser")

    title = ""
    og_title = soup.find("meta", attrs={"property": "og:title"})
    if og_title and og_title.get("content"):
        title = og_title["content"].strip()
    elif soup.title and soup.title.string:
        title = soup.title.string.strip()

    icon = ""
    for rel in (["icon"], ["shortcut", "icon"], ["apple-touch-icon"]):
        link = soup.find("link", rel=rel)
        if link and link.get("href"):
            icon = urljoin(page_url, link["href"])
            break

    if not icon:
        icon = urljoin(page_url, "/favicon.ico")

    return {"title": title, "icon": icon}
