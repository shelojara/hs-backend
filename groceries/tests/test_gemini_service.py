from unittest.mock import MagicMock, patch

from groceries import gemini_service
from groceries.gemini_service import LiderProductInfo, _parse_lider_product_payload


@patch("groceries.gemini_service._get_client")
def test_fetch_lider_product_info_returns_structured_fields(mock_get_client):
    mock_response = MagicMock()
    mock_response.text = (
        '{"brand": "Colún", "price": "$2.590", "format": "1 L", '
        '"details": "Leche entera, góndola lácteos."}'
    )
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response
    mock_get_client.return_value = mock_client

    out = gemini_service.fetch_lider_product_info(product_name="  Leche  ")

    assert out == LiderProductInfo(
        brand="Colún",
        price="$2.590",
        format="1 L",
        details="Leche entera, góndola lácteos.",
    )
    mock_client.models.generate_content.assert_called_once()
    cfg = mock_client.models.generate_content.call_args.kwargs["config"]
    assert cfg.tools


@patch("groceries.gemini_service._get_client")
def test_fetch_lider_product_info_strips_json_fence(mock_get_client):
    mock_response = MagicMock()
    mock_response.text = """```json
{"brand": "", "price": "", "format": "500 g", "details": "Arroz."}
```"""
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response
    mock_get_client.return_value = mock_client

    out = gemini_service.fetch_lider_product_info(product_name="Arroz")
    assert out == LiderProductInfo(
        brand="",
        price="",
        format="500 g",
        details="Arroz.",
    )


@patch("groceries.gemini_service._get_client")
def test_fetch_lider_product_info_empty_name_returns_none(mock_get_client):
    assert gemini_service.fetch_lider_product_info(product_name="   ") is None
    mock_get_client.assert_not_called()


def test_parse_legacy_plain_text_maps_to_details_only():
    out = _parse_lider_product_payload("  Solo texto.  ")
    assert out == LiderProductInfo(
        brand="",
        price="",
        format="",
        details="Solo texto.",
    )


def test_parse_invalid_json_falls_back_to_plain_text():
    out = _parse_lider_product_payload("{not json")
    assert out == LiderProductInfo(
        brand="",
        price="",
        format="",
        details="{not json",
    )
