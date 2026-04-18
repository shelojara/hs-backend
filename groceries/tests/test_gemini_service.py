from decimal import Decimal
from unittest.mock import MagicMock, patch

from groceries import gemini_service
from groceries.gemini_service import (
    LiderProductInfo,
    _parse_lider_product_list_payload,
    _parse_lider_product_payload,
)


@patch("groceries.gemini_service._get_client")
def test_fetch_lider_product_info_returns_structured_fields(mock_get_client):
    mock_response = MagicMock()
    mock_response.text = (
        '{"display_name": "Colún Leche Entera 1 L", "standard_name": "Leche entera", '
        '"brand": "Colún", "price": 2590, '
        '"format": "1 L", '
        '"emoji": "🥛"}'
    )
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response
    mock_get_client.return_value = mock_client

    out = gemini_service.fetch_lider_product_info(product_name="  Leche  ")

    assert out == LiderProductInfo(
        display_name="Colún Leche Entera 1 L",
        standard_name="Leche entera",
        brand="Colún",
        price=Decimal("2590.00"),
        format="1 L",
        emoji="🥛",
    )
    mock_client.models.generate_content.assert_called_once()
    cfg = mock_client.models.generate_content.call_args.kwargs["config"]
    assert cfg.tools


@patch("groceries.gemini_service._get_client")
def test_fetch_lider_product_info_strips_json_fence(mock_get_client):
    mock_response = MagicMock()
    mock_response.text = """```json
{"display_name": "", "standard_name": "Arroz grano largo", "brand": "", "price": 0, "format": "500 g", "emoji": ""}
```"""
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response
    mock_get_client.return_value = mock_client

    out = gemini_service.fetch_lider_product_info(product_name="Arroz")
    assert out == LiderProductInfo(
        display_name="",
        standard_name="Arroz grano largo",
        brand="",
        price=Decimal("0"),
        format="500 g",
        emoji="",
    )


@patch("groceries.gemini_service._get_client")
def test_fetch_lider_product_info_empty_name_returns_none(mock_get_client):
    assert gemini_service.fetch_lider_product_info(product_name="   ") is None
    mock_get_client.assert_not_called()


def test_parse_plain_text_without_json_returns_none():
    assert _parse_lider_product_payload("  Solo texto.  ") is None


def test_parse_invalid_json_returns_none():
    assert _parse_lider_product_payload("{not json") is None


def test_parse_lider_product_list_payload_array():
    raw = (
        '[{"display_name": "A", "standard_name": "Sa", "brand": "", "price": 100, '
        '"format": "", "emoji": ""}, '
        '{"display_name": "B", "standard_name": "Sb", "brand": "X", "price": 0, '
        '"format": "1 L", "emoji": "🥛"}]'
    )
    out = _parse_lider_product_list_payload(raw, max_items=10)
    assert len(out) == 2
    assert out[0].display_name == "A"
    assert out[1].format == "1 L"


def test_parse_lider_product_list_payload_caps_max_items():
    raw = "[" + ",".join(
        '{"display_name": "P", "standard_name": "", "brand": "", "price": 0, "format": "", "emoji": ""}'
        for _ in range(12)
    )
    raw += "]"
    out = _parse_lider_product_list_payload(raw, max_items=10)
    assert len(out) == 10


def test_parse_lider_product_list_payload_wraps_single_object():
    raw = '{"display_name": "Solo", "standard_name": "", "brand": "", "price": 5, "format": "", "emoji": ""}'
    out = _parse_lider_product_list_payload(raw, max_items=10)
    assert len(out) == 1
    assert out[0].display_name == "Solo"


@patch("groceries.gemini_service._get_client")
def test_fetch_lider_product_candidates_returns_list(mock_get_client):
    mock_response = MagicMock()
    mock_response.text = (
        '[{"display_name": "One", "standard_name": "T", "brand": "", "price": 1, '
        '"format": "", "emoji": ""}]'
    )
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response
    mock_get_client.return_value = mock_client

    out = gemini_service.fetch_lider_product_candidates(query="  milk  ")
    assert len(out) == 1
    assert out[0].display_name == "One"
    mock_client.models.generate_content.assert_called_once()
    cfg = mock_client.models.generate_content.call_args.kwargs["config"]
    assert "array" in (cfg.system_instruction or "").lower()
