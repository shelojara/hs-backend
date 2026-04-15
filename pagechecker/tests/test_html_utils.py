"""Regression tests for HTML parsing edge cases (malformed / odd bs4 trees)."""

from bs4 import BeautifulSoup

from pagechecker.html_utils import (
    _chrome_id_class_blob,
    _strip_nav_and_footer,
    extract_body_html,
    extract_metadata,
)


def test_chrome_id_class_blob_handles_none_attrs():
    soup = BeautifulSoup('<div id="navbar-x">x</div>', "html.parser")
    div = soup.find("div")
    assert div is not None
    div.attrs = None
    assert _chrome_id_class_blob(div) == ""


def test_strip_nav_and_footer_no_crash_when_attrs_none():
    soup = BeautifulSoup(
        '<body><div role="navigation">n</div><p id="keep">ok</p></body>',
        "html.parser",
    )
    body = soup.body
    assert body is not None
    for tag in body.find_all(attrs={"role": True}):
        tag.attrs = None
    _strip_nav_and_footer(body)
    assert "keep" in body.decode()


def test_extract_body_html_no_crash_when_role_tag_attrs_none():
    html = "<html><body><div role='navigation'>n</div><main>hi</main></body></html>"
    soup = BeautifulSoup(html, "html.parser")
    body = soup.body
    assert body is not None
    for tag in body.find_all(attrs={"role": True}):
        tag.attrs = None
    out = extract_body_html(str(soup))
    assert "hi" in out


def test_extract_metadata_og_title_no_crash_when_meta_attrs_none():
    html = (
        '<html><head>'
        '<meta property="og:title" content="T">'
        '<title>Fallback</title></head><body></body></html>'
    )
    soup = BeautifulSoup(html, "html.parser")
    meta = soup.find("meta", attrs={"property": "og:title"})
    assert meta is not None
    meta.attrs = None
    md = extract_metadata(str(soup), "https://example.com/page")
    assert md["title"] == "Fallback"


def test_extract_metadata_link_href_no_crash_when_link_attrs_none():
    html = (
        '<html><head><link rel="icon" href="/f.ico">'
        "<title>T</title></head><body></body></html>"
    )
    soup = BeautifulSoup(html, "html.parser")
    link = soup.find("link")
    assert link is not None
    link.attrs = None
    md = extract_metadata(str(soup), "https://example.com/page")
    assert md["title"] == "T"
    assert md["icon"] == "https://example.com/favicon.ico"
