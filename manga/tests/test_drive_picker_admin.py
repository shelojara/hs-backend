"""Staff JSON endpoint for Google Picker (admin)."""

from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

User = get_user_model()


@pytest.mark.django_db
def test_picker_token_requires_staff():
    client = Client()
    u = User.objects.create_user("u1", "u1@x.com", "x")
    u.is_staff = False
    u.save()
    client.force_login(u)
    r = client.get(reverse("admin_manga_gdrive_picker_token"))
    assert r.status_code == 302


@pytest.mark.django_db
def test_picker_token_returns_json():
    from manga.models import GoogleDriveApplicationCredentials

    client = Client()
    u = User.objects.create_user("staff1", "s1@x.com", "x")
    u.is_staff = True
    u.save()
    client.force_login(u)
    GoogleDriveApplicationCredentials.objects.update_or_create(
        pk=1,
        defaults={"client_id": "c", "client_secret": "s", "developer_key": "k"},
    )
    payload = {
        "access_token": "t",
        "expires_in": 300,
        "api_key": "k",
    }
    with patch("manga.drive_picker_admin_views.picker_access_token_payload", return_value=payload):
        r = client.get(reverse("admin_manga_gdrive_picker_token"))
    assert r.status_code == 200
    data = r.json()
    assert data == payload
