from urllib.parse import urljoin

from bs4 import BeautifulSoup
from bs4.element import Tag
from markdownify import markdownify

_CHROME_ROLE = frozenset({"navigation", "contentinfo"})


def _tag_get(tag: Tag, key: str, default=None):
    """bs4 Tag.get assumes attrs dict; rare malformed trees leave attrs None."""
    attrs = getattr(tag, "attrs", None)
    if attrs is None:
        return default
    return attrs.get(key, default)


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
    tid = _tag_get(tag, "id")
    if isinstance(tid, str):
        parts.append(tid)
    classes = _tag_get(tag, "class")
    if isinstance(classes, list):
        parts.extend(str(c) for c in classes)
    elif isinstance(classes, str):
        parts.append(classes)
    return " ".join(parts).lower()


def _strip_nav_and_footer(body: Tag) -> None:
    """Remove nav bars and footers from body (semantic tags, roles, common id/class)."""
    for tag in body.find_all(["nav", "footer"]):
        tag.decompose()

    # Avoid attrs={"role": True}: bs4 matcher calls Tag.get; attrs can be None on bad markup.
    for tag in body.find_all(True):
        if not isinstance(tag, Tag):
            continue
        role = (_tag_get(tag, "role") or "").strip().lower()
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
    for meta in soup.find_all("meta"):
        prop = (_tag_get(meta, "property") or "").strip().lower()
        if prop != "og:title":
            continue
        content = _tag_get(meta, "content")
        if content:
            title = str(content).strip()
            break
    if not title and soup.title and soup.title.string:
        title = soup.title.string.strip()

    def _link_rel_matches(tag: Tag, want: list[str]) -> bool:
        raw = _tag_get(tag, "rel")
        if raw is None:
            return False
        if isinstance(raw, list):
            have = {str(x).lower() for x in raw}
        else:
            have = {x.lower() for x in str(raw).split()}
        return {w.lower() for w in want} <= have

    icon = ""
    for rel in (["icon"], ["shortcut", "icon"], ["apple-touch-icon"]):
        for link in soup.find_all("link"):
            if not isinstance(link, Tag):
                continue
            if not _link_rel_matches(link, rel):
                continue
            href = _tag_get(link, "href")
            if href:
                icon = urljoin(page_url, str(href))
                break
        if icon:
            break

    if not icon:
        icon = urljoin(page_url, "/favicon.ico")

    return {"title": title, "icon": icon}
