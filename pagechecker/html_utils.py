from urllib.parse import urljoin

from bs4 import BeautifulSoup
from markdownify import markdownify as _markdownify


def extract_body_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    body = soup.body or soup

    for tag in body.find_all(["script", "style"]):
        tag.decompose()

    return body.get_text(separator="\n", strip=True)


def extract_body_html(html: str) -> str:
    """Return inner HTML of the document body (no head/doctype), scripts/styles removed."""
    soup = BeautifulSoup(html, "html.parser")
    body = soup.body or soup

    for tag in body.find_all(["script", "style"]):
        tag.decompose()

    return body.decode_contents()


def html_to_markdown(html: str) -> str:
    """Convert HTML fragment to Markdown (python-markdownify)."""
    fragment = html or ""
    if not fragment.strip():
        return ""
    return _markdownify(fragment, heading_style="ATX").strip()


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
