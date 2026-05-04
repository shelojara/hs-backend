"""Google Drive OAuth PKCE verifier must survive redirect (stored in session)."""

from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from manga.drive_oauth_admin_views import SESSION_CODE_VERIFIER_KEY
from manga.models import GoogleDriveApplicationCredentials


@pytest.fixture
def superuser(db):
    User = get_user_model()
    return User.objects.create_superuser("oauth_admin", "oauth@example.com", "test-pass")


@pytest.mark.django_db
def test_oauth_start_stores_code_verifier_in_session(superuser):
    GoogleDriveApplicationCredentials.objects.update_or_create(
        pk=1,
        defaults={
            "client_id": "cid.apps.googleusercontent.com",
            "client_secret": "csecret",
        },
    )
    client = Client()
    client.force_login(superuser)
    with patch("manga.drive_oauth_admin_views.Flow") as MockFlow:
        mock_flow = MockFlow.from_client_config.return_value
        mock_flow.authorization_url.return_value = ("https://accounts.google.com/o/oauth2/auth?x=1", "st")
        mock_flow.code_verifier = "pkce-verifier-abc"
        response = client.get(reverse("admin_manga_gdrive_oauth_start"))
    assert response.status_code == 302
    assert client.session.get(SESSION_CODE_VERIFIER_KEY) == "pkce-verifier-abc"


@pytest.mark.django_db
def test_oauth_callback_passes_session_code_verifier_to_flow(superuser):
    GoogleDriveApplicationCredentials.objects.update_or_create(
        pk=1,
        defaults={
            "client_id": "cid.apps.googleusercontent.com",
            "client_secret": "csecret",
        },
    )
    client = Client()
    client.force_login(superuser)
    session = client.session
    session[SESSION_CODE_VERIFIER_KEY] = "roundtrip-verifier"
    session.save()

    callback_path = reverse("admin_manga_gdrive_oauth_callback")
    with patch("manga.drive_oauth_admin_views.Flow") as MockFlow:
        mock_flow = MockFlow.from_client_config.return_value
        mock_flow.credentials = type(
            "C",
            (),
            {
                "refresh_token": "rt",
                "token": "at",
                "expiry": None,
            },
        )()
        client.get(
            callback_path,
            {"code": "auth-code", "state": "ignored-by-google-flow"},
            HTTP_HOST="localhost",
        )
        _, kwargs = MockFlow.from_client_config.call_args
        assert kwargs.get("code_verifier") == "roundtrip-verifier"
        mock_flow.fetch_token.assert_called_once()


@pytest.mark.django_db
def test_oauth_callback_without_session_verifier_redirects_with_error(superuser):
    GoogleDriveApplicationCredentials.objects.update_or_create(
        pk=1,
        defaults={
            "client_id": "cid.apps.googleusercontent.com",
            "client_secret": "csecret",
        },
    )
    client = Client()
    client.force_login(superuser)
    assert SESSION_CODE_VERIFIER_KEY not in client.session
    response = client.get(
        reverse("admin_manga_gdrive_oauth_callback"),
        {"code": "x"},
        HTTP_HOST="localhost",
        follow=True,
    )
    assert response.status_code == 200
    content = b"".join(response.streaming_content) if response.streaming else response.content
    assert b"PKCE" in content or b"Start Google OAuth" in content
