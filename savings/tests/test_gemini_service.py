"""Tests for savings Gemini helpers."""

from unittest.mock import MagicMock, patch

from savings import gemini_service


@patch("savings.gemini_service._get_client")
def test_suggest_asset_emoji_returns_first_glyph(mock_get_client):
    mock_response = MagicMock()
    mock_response.text = "✈️"
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response
    mock_get_client.return_value = mock_client

    assert gemini_service.suggest_asset_emoji(name="Trip fund") == "✈️"


@patch("savings.gemini_service._get_client")
def test_suggest_asset_emoji_empty_fallback(mock_get_client):
    mock_response = MagicMock()
    mock_response.text = ""
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response
    mock_get_client.return_value = mock_client

    assert gemini_service.suggest_asset_emoji(name="X") == "💰"
