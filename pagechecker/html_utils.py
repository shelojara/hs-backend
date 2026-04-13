import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Comment

# Tags removed entirely (no LLM signal vs noise).
_REMOVE_TAGS = frozenset(
    {
        "script",
        "style",
        "noscript",
        "iframe",
        "object",
        "embed",
        "template",
        "link",
        "meta",
        "svg",
        "canvas",
        "video",
        "audio",
        "source",
    }
)

# Wrapper tags whose children should stay; unwrap before other cleanup.
_UNWRAP_TAGS = frozenset({"picture", "font", "center"})

# Event-handler attributes: onload, onclick, etc. (not `once`).
_EVENT_ATTR = re.compile(r"^on[a-z]")


def _strip_comments(body) -> None:
    for node in body.find_all(string=True):
        if isinstance(node, Comment):
            node.extract()


def _unwrap_tags(body, names: frozenset[str]) -> None:
    for name in names:
        for tag in list(body.find_all(name)):
            tag.unwrap()


def _decompose_tags(body, names: frozenset[str]) -> None:
    for name in names:
        for tag in body.find_all(name):
            tag.decompose()


def _should_drop_attr(name: str) -> bool:
    ln = name.lower()
    if ln.startswith("data-"):
        return True
    if ln.startswith("aria-"):
        return True
    if _EVENT_ATTR.match(ln):
        return True
    if ln == "xmlns" or ln.startswith("xmlns:"):
        return True
    return ln in _DROP_ATTRS


_DROP_ATTRS = frozenset(
    {
        "style",
        "class",
        "id",
        "role",
        "tabindex",
        "draggable",
        "contenteditable",
        "spellcheck",
        "translate",
        "hidden",
        "loading",
        "decoding",
        "fetchpriority",
        "referrerpolicy",
        "crossorigin",
        "integrity",
        "nonce",
        "sizes",
        "srcset",
        "width",
        "height",
        "align",
        "valign",
        "bgcolor",
        "border",
        "cellpadding",
        "cellspacing",
        "face",
        "color",
        "ping",
        "importance",
        "slot",
        "part",
        "popover",
        "popovertarget",
        "popovertargetaction",
        "inert",
        "enterkeyhint",
        "inputmode",
        "autocapitalize",
        "autocorrect",
        "itemscope",
        "itemtype",
        "itemprop",
        "itemid",
        "itemref",
        "accesskey",
        "autocomplete",
        "dirname",
        "form",
        "formaction",
        "formenctype",
        "formmethod",
        "formnovalidate",
        "formtarget",
        "list",
        "maxlength",
        "minlength",
        "multiple",
        "pattern",
        "readonly",
        "required",
        "step",
        "autofocus",
        "results",
        "autosave",
        "incremental",
        "icon",
        "manifest",
        "media",
        "blocking",
        "imagesizes",
        "imagesrcset",
    }
)


def _strip_noise_attributes(body) -> None:
    for tag in body.find_all(True):
        if not tag.attrs:
            continue
        for attr in list(tag.attrs):
            if _should_drop_attr(attr):
                del tag[attr]


def _sanitize_body_tree(body) -> None:
    _strip_comments(body)
    _unwrap_tags(body, _UNWRAP_TAGS)
    _decompose_tags(body, _REMOVE_TAGS)
    _strip_noise_attributes(body)


def extract_body_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    body = soup.body or soup
    _sanitize_body_tree(body)
    return body.get_text(separator="\n", strip=True)


def extract_body_html(html: str) -> str:
    """Return inner HTML of document body: no head/doctype, scripts/styles and noisy attrs stripped."""
    soup = BeautifulSoup(html, "html.parser")
    body = soup.body or soup
    _sanitize_body_tree(body)
    return body.decode_contents()


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
