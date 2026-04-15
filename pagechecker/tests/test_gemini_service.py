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


def test_suggest_page_category_id_empty_list_returns_none():
    assert (
        gemini_service.suggest_page_category_id(
            page_url="https://a.test/",
            page_title="",
            categories=[],
        )
        is None
    )


@patch("pagechecker.gemini_service._get_client")
def test_suggest_page_category_id_parses_id(mock_get_client):
    mock_response = MagicMock()
    mock_response.text = "  12  "
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response
    mock_get_client.return_value = mock_client

    out = gemini_service.suggest_page_category_id(
        page_url="https://x.test/",
        page_title="T",
        categories=[{"id": 12, "name": "News", "examples": []}],
    )
    assert out == 12


@patch("pagechecker.gemini_service._get_client")
def test_suggest_page_category_id_none_reply(mock_get_client):
    mock_response = MagicMock()
    mock_response.text = "NONE"
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response
    mock_get_client.return_value = mock_client

    assert (
        gemini_service.suggest_page_category_id(
            page_url="https://x.test/",
            page_title="",
            categories=[{"id": 1, "name": "A", "examples": []}],
        )
        is None
    )


@patch("pagechecker.gemini_service._get_client")
def test_suggest_page_category_id_unknown_id_returns_none(mock_get_client):
    mock_response = MagicMock()
    mock_response.text = "999"
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response
    mock_get_client.return_value = mock_client

    assert (
        gemini_service.suggest_page_category_id(
            page_url="https://x.test/",
            page_title="",
            categories=[{"id": 1, "name": "A", "examples": []}],
        )
        is None
    )
