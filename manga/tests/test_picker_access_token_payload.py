"""picker_access_token_payload (Google Picker in admin)."""

from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from django.utils import timezone

from manga.models import GoogleDriveApplicationCredentials


@pytest.mark.django_db
def test_picker_access_token_requires_developer_key():
    GoogleDriveApplicationCredentials.objects.update_or_create(
        pk=1,
        defaults={
            "client_id": "id.apps.googleusercontent.com",
            "client_secret": "sec",
            "refresh_token": "r",
            "developer_key": "",
        },
    )
    mock_creds = MagicMock()
    mock_creds.expired = False
    mock_creds.token = "atoken"

    from manga import google_drive_service as gds

    with patch.object(gds, "_drive_credentials", return_value=mock_creds):
        with pytest.raises(RuntimeError, match="Developer API key"):
            gds.picker_access_token_payload()


@pytest.mark.django_db
def test_picker_access_token_payload_structure():
    GoogleDriveApplicationCredentials.objects.update_or_create(
        pk=1,
        defaults={
            "client_id": "id.apps.googleusercontent.com",
            "client_secret": "sec",
            "refresh_token": "r",
            "developer_key": "browser-key",
        },
    )
    mock_creds = MagicMock()
    mock_creds.expired = False
    mock_creds.token = "atoken"
    mock_creds.expiry = timezone.now() + timedelta(seconds=120)

    from manga import google_drive_service as gds

    with patch.object(gds, "_drive_credentials", return_value=mock_creds):
        out = gds.picker_access_token_payload()

    assert out["access_token"] == "atoken"
    assert out["api_key"] == "browser-key"
    assert out["expires_in"] >= 60


@pytest.mark.django_db
def test_drive_parent_folder_prefers_database_over_settings(settings):
    from manga.google_drive_service import _drive_parent_for_root_folder

    settings.MANGA_GOOGLE_DRIVE_PARENT_FOLDER_ID = "from-settings"
    GoogleDriveApplicationCredentials.objects.update_or_create(
        pk=1,
        defaults={"parent_folder_id": "from-db"},
    )
    assert _drive_parent_for_root_folder() == "from-db"


@pytest.mark.django_db
def test_drive_parent_folder_falls_back_to_settings(settings):
    from manga.google_drive_service import _drive_parent_for_root_folder

    settings.MANGA_GOOGLE_DRIVE_PARENT_FOLDER_ID = "from-settings"
    GoogleDriveApplicationCredentials.objects.update_or_create(
        pk=1,
        defaults={"parent_folder_id": ""},
    )
    assert _drive_parent_for_root_folder() == "from-settings"
