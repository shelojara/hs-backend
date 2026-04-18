from unittest.mock import MagicMock, patch

from groceries import gemini_service


@patch("groceries.gemini_service._get_client")
def test_fetch_lider_product_details_returns_normalized_text(mock_get_client):
    mock_response = MagicMock()
    mock_response.text = "  Líder: leche 1 L.  "
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response
    mock_get_client.return_value = mock_client

    out = gemini_service.fetch_lider_product_details(product_name="  Leche  ")

    assert out == "Líder: leche 1 L."
    mock_client.models.generate_content.assert_called_once()
    cfg = mock_client.models.generate_content.call_args.kwargs["config"]
    assert cfg.tools


@patch("groceries.gemini_service._get_client")
def test_fetch_lider_product_details_empty_name_returns_none(mock_get_client):
    assert gemini_service.fetch_lider_product_details(product_name="   ") is None
    mock_get_client.assert_not_called()
