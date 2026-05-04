"""Google Drive OAuth uses HTTPS redirect_uri for Google Cloud Console."""

import pytest
from django.test import RequestFactory
from django.urls import reverse

from manga.drive_oauth_admin_views import _public_https_url, _redirect_uri


def test_public_https_url_upgrades_http_to_https():
    rf = RequestFactory()
    req = rf.get("/foo", secure=False, HTTP_HOST="localhost")
    assert _public_https_url(req) == "https://localhost/foo"


def test_public_https_url_keeps_https():
    rf = RequestFactory()
    req = rf.get("/foo", secure=True, HTTP_HOST="localhost")
    assert _public_https_url(req) == "https://localhost/foo"


@pytest.mark.django_db
def test_redirect_uri_is_https_even_when_request_is_http():
    rf = RequestFactory()
    path = reverse("admin_manga_gdrive_oauth_callback")
    req = rf.get(path, secure=False, HTTP_HOST="localhost")
    uri = _redirect_uri(req)
    assert uri.startswith("https://")
    assert path in uri
