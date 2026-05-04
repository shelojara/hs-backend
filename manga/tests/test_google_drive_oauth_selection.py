"""Google Drive OAuth credentials used for API client."""

from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.django_db
def test_drive_service_uses_oauth_when_refresh_token_configured():
    from manga.google_drive_service import _drive_service
    from manga.models import GoogleDriveApplicationCredentials

    GoogleDriveApplicationCredentials.objects.update_or_create(
        pk=1,
        defaults={
            "client_id": "test-client-id.apps.googleusercontent.com",
            "client_secret": "secret",
            "refresh_token": "refresh-token-value",
            "access_token": "existing-access",
        },
    )
    mock_oauth = MagicMock()
    mock_oauth.expired = False
    mock_oauth.token = "existing-access"
    with (
        patch("manga.google_drive_service._oauth_credentials", return_value=mock_oauth) as mock_oauth_fn,
        patch("manga.google_drive_service.build") as mock_build,
    ):
        mock_build.return_value = MagicMock()
        _drive_service()
    mock_oauth_fn.assert_called_once()
    mock_build.assert_called_once()
    assert mock_build.call_args.kwargs["credentials"] is mock_oauth


@pytest.mark.django_db
def test_drive_service_raises_when_oauth_not_configured():
    from manga.google_drive_service import _drive_service
    from manga.models import GoogleDriveApplicationCredentials

    GoogleDriveApplicationCredentials.objects.filter(pk=1).delete()
    with pytest.raises(RuntimeError, match="Google Drive not configured"):
        _drive_service()
