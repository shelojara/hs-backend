"""Google Drive Picker admin (superuser + server-minted access token)."""

from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

User = get_user_model()


@pytest.fixture
def superuser(db):
    return User.objects.create_superuser("picker_su", "su@example.com", "pw")


@pytest.fixture
def staff_not_super(db):
    return User.objects.create_user("picker_staff", "st@example.com", "pw", is_staff=True)


def test_picker_get_requires_login():
    r = Client().get(reverse("admin_manga_gdrive_picker"))
    assert r.status_code in (302, 403)
    if r.status_code == 302:
        assert "login" in r.url.lower()


def test_picker_get_superuser_200(superuser):
    c = Client()
    c.force_login(superuser)
    r = c.get(reverse("admin_manga_gdrive_picker"))
    assert r.status_code == 200
    assert b"Google Drive Picker" in r.content


def test_picker_get_staff_forbidden(staff_not_super):
    c = Client()
    c.force_login(staff_not_super)
    r = c.get(reverse("admin_manga_gdrive_picker"))
    assert r.status_code == 302


@patch("manga.drive_picker_admin_views.get_drive_access_token_for_picker", return_value="tok_test")
def test_picker_token_post_returns_json(mock_token, superuser):
    c = Client()
    c.force_login(superuser)
    url = reverse("admin_manga_gdrive_picker_token")
    r = c.post(url, content_type="application/json", data="{}")
    assert r.status_code == 200
    assert r.json() == {"access_token": "tok_test"}
    mock_token.assert_called_once()


@patch(
    "manga.drive_picker_admin_views.get_drive_access_token_for_picker",
    side_effect=RuntimeError("not configured"),
)
def test_picker_token_post_503_on_runtime_error(_mock, superuser):
    c = Client()
    c.force_login(superuser)
    r = c.post(
        reverse("admin_manga_gdrive_picker_token"),
        content_type="application/json",
        data="{}",
    )
    assert r.status_code == 503
    assert "not configured" in r.json()["error"]


def test_picker_token_post_anonymous():
    r = Client().post(
        reverse("admin_manga_gdrive_picker_token"),
        content_type="application/json",
        data="{}",
    )
    assert r.status_code in (302, 403)
