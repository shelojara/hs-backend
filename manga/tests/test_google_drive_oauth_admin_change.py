"""Google Drive OAuth admin change page renders without TypeError."""

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from manga.models import GoogleDriveApplicationCredentials

User = get_user_model()


@pytest.mark.django_db
def test_google_drive_oauth_change_page_ok():
    GoogleDriveApplicationCredentials.objects.update_or_create(
        pk=1,
        defaults={"client_id": "x.apps.googleusercontent.com", "client_secret": "s"},
    )
    client = Client()
    u = User.objects.create_superuser("su", "su@x.com", "pw")
    client.force_login(u)
    url = reverse("admin:manga_googledriveapplicationcredentials_change", args=(1,))
    r = client.get(url)
    assert r.status_code == 200


@pytest.mark.django_db
def test_google_drive_oauth_change_form_post_no_fake_field_error():
    GoogleDriveApplicationCredentials.objects.update_or_create(
        pk=1,
        defaults={
            "client_id": "x.apps.googleusercontent.com",
            "client_secret": "secret",
            "refresh_token": "r",
        },
    )
    client = Client()
    u = User.objects.create_superuser("su2", "su2@x.com", "pw")
    client.force_login(u)
    url = reverse("admin:manga_googledriveapplicationcredentials_change", args=(1,))
    r = client.get(url)
    assert r.status_code == 200
    post = client.post(
        url,
        {
            "client_id": "x.apps.googleusercontent.com",
            "client_secret": "secret",
            "refresh_token": "r",
            "access_token": "",
            "access_token_expires_at": "",
            "token_uri": "https://oauth2.googleapis.com/token",
            "_save": "Save",
        },
    )
    assert post.status_code == 302
