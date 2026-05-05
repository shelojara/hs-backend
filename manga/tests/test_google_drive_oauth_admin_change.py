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
