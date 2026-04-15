from unittest.mock import MagicMock, patch

from pagechecker import gemini_service


@patch("pagechecker.gemini_service._get_client")
def test_suggest_category_emoji_strips_and_truncates(mock_get_client):
    mock_response = MagicMock()
    mock_response.text = '  "🚀"  '
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response
    mock_get_client.return_value = mock_client

    assert gemini_service.suggest_category_emoji("Space") == "🚀"
    mock_client.models.generate_content.assert_called_once()


@patch("pagechecker.gemini_service._get_client")
def test_suggest_category_emoji_empty_response_uses_fallback(mock_get_client):
    mock_response = MagicMock()
    mock_response.text = "   "
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response
    mock_get_client.return_value = mock_client

    assert gemini_service.suggest_category_emoji("Misc") == "📁"
