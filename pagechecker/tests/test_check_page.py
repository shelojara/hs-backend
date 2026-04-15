import json
from unittest.mock import MagicMock, patch

import httpx
import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from pagechecker.models import Page
from pagechecker.services import MonitoredUrlNotFoundError, check_page

User = get_user_model()


@pytest.mark.django_db
def test_check_page_raises_monitored_url_not_found_on_http_404():
    page = Page.objects.create(url="https://example.com/missing")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, request=request)

    transport = httpx.MockTransport(handler)

    def fake_get(url: str, verify: bool = False) -> httpx.Response:
        with httpx.Client(transport=transport) as client:
            return client.get(url)

    with patch("pagechecker.services.httpx.get", new=fake_get):
        with pytest.raises(MonitoredUrlNotFoundError) as exc_info:
            check_page(page.id)
    assert "404" in str(exc_info.value)
    assert "Not Found" in str(exc_info.value)


@pytest.mark.django_db
def test_check_page_api_returns_clear_detail_on_remote_404():
    User.objects.create_user(username="check404", password="secret404")
    page = Page.objects.create(url="https://example.com/missing")

    api_client = Client()
    login_resp = api_client.post(
        "/api/v1.Auth.Login",
        data=json.dumps({"username": "check404", "password": "secret404"}),
        content_type="application/json",
    )
    assert login_resp.status_code == 200
    token = login_resp.json()["access_token"]

    with patch("pagechecker.services.httpx.get") as mock_get:
        mock_get.return_value = MagicMock(status_code=404, text="")
        check_resp = api_client.post(
            "/api/v1.PageChecker.CheckPage",
            data=json.dumps({"page_id": page.id}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

    assert check_resp.status_code == 404
    body = check_resp.json()
    assert "detail" in body
    assert "404" in body["detail"]
    assert "Not Found" in body["detail"]
