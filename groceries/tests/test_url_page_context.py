from groceries.url_page_context import html_to_plain_text, is_http_https_url


def test_is_http_https_url_recognizes_full_urls():
    assert is_http_https_url("https://www.jumbo.cl/foo")
    assert is_http_https_url("http://127.0.0.1:8000/x")
    assert is_http_https_url("www.lider.cl/producto")


def test_is_http_https_url_rejects_bare_host_without_dot():
    assert not is_http_https_url("milk")
    assert not is_http_https_url("leche")


def test_html_to_plain_text_strips_scripts():
    html = "<html><body><script>x</script><p>Hello</p></body></html>"
    assert html_to_plain_text(html) == "Hello"
