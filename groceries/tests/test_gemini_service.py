from decimal import Decimal
from unittest.mock import MagicMock, patch

from groceries import gemini_service
from groceries.gemini_service import (
    MerchantProductInfo,
    PreferredMerchantContext,
    RunningLowSuggestion,
    _parse_merchant_product_list_payload,
    _parse_merchant_product_payload,
    _parse_running_low_suggestions,
    merchant_product_find_system_instruction,
    merchant_product_single_system_instruction,
    running_low_instruction_with_merchants,
)


@patch("groceries.gemini_service._get_client")
def test_fetch_merchant_product_info_returns_structured_fields(mock_get_client):
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

    out = gemini_service.fetch_merchant_product_info(product_name="  Leche  ")

    assert out == MerchantProductInfo(
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
def test_fetch_merchant_product_info_strips_json_fence(mock_get_client):
    mock_response = MagicMock()
    mock_response.text = """```json
{"display_name": "", "standard_name": "Arroz grano largo", "brand": "", "price": 0, "format": "500 g", "emoji": ""}
```"""
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response
    mock_get_client.return_value = mock_client

    out = gemini_service.fetch_merchant_product_info(product_name="Arroz")
    assert out == MerchantProductInfo(
        display_name="",
        standard_name="Arroz grano largo",
        brand="",
        price=Decimal("0"),
        format="500 g",
        emoji="",
    )


@patch("groceries.gemini_service._get_client")
def test_fetch_merchant_product_info_empty_name_returns_none(mock_get_client):
    assert gemini_service.fetch_merchant_product_info(product_name="   ") is None
    mock_get_client.assert_not_called()


@patch("groceries.gemini_service._get_client")
def test_fetch_merchant_product_info_by_identity_empty_standard_name_returns_none(
    mock_get_client,
):
    assert (
        gemini_service.fetch_merchant_product_info_by_identity(
            standard_name="   ",
            brand="Colún",
            format="1 L",
        )
        is None
    )
    mock_get_client.assert_not_called()


@patch("groceries.gemini_service._get_client")
def test_fetch_merchant_product_info_by_identity_parses_json(mock_get_client):
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

    out = gemini_service.fetch_merchant_product_info_by_identity(
        standard_name="Leche entera",
        brand="Colún",
        format="1 L",
    )

    assert out == MerchantProductInfo(
        display_name="Colún Leche Entera 1 L",
        standard_name="Leche entera",
        brand="Colún",
        price=Decimal("2590.00"),
        format="1 L",
        emoji="🥛",
    )
    mock_client.models.generate_content.assert_called_once()
    call_kw = mock_client.models.generate_content.call_args.kwargs
    assert "Leche entera" in call_kw["contents"]
    assert "Colún" in call_kw["contents"]


def test_parse_plain_text_without_json_returns_none():
    assert _parse_merchant_product_payload("  Solo texto.  ") is None


def test_parse_invalid_json_returns_none():
    assert _parse_merchant_product_payload("{not json") is None


def test_parse_merchant_product_list_payload_array():
    raw = (
        '[{"display_name": "A", "standard_name": "Sa", "brand": "", "price": 100, '
        '"format": "", "emoji": ""}, '
        '{"display_name": "B", "standard_name": "Sb", "brand": "X", "price": 0, '
        '"format": "1 L", "emoji": "🥛"}]'
    )
    out = _parse_merchant_product_list_payload(raw, max_items=10)
    assert len(out) == 2
    assert out[0].display_name == "A"
    assert out[1].format == "1 L"


def test_parse_merchant_product_list_payload_caps_max_items():
    raw = "[" + ",".join(
        '{"display_name": "P", "standard_name": "", "brand": "", "price": 0, "format": "", "emoji": ""}'
        for _ in range(12)
    )
    raw += "]"
    out = _parse_merchant_product_list_payload(raw, max_items=10)
    assert len(out) == 10


def test_parse_merchant_product_list_payload_wraps_single_object():
    raw = '{"display_name": "Solo", "standard_name": "", "brand": "", "price": 5, "format": "", "emoji": ""}'
    out = _parse_merchant_product_list_payload(raw, max_items=10)
    assert len(out) == 1
    assert out[0].display_name == "Solo"


@patch("groceries.gemini_service._get_client")
def test_fetch_merchant_product_candidates_returns_list(mock_get_client):
    mock_response = MagicMock()
    mock_response.text = (
        '[{"display_name": "One", "standard_name": "T", "brand": "", "price": 1, '
        '"format": "", "emoji": ""}]'
    )
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response
    mock_get_client.return_value = mock_client

    out = gemini_service.fetch_merchant_product_candidates(query="  milk  ")
    assert len(out) == 1
    assert out[0].display_name == "One"
    mock_client.models.generate_content.assert_called_once()
    cfg = mock_client.models.generate_content.call_args.kwargs["config"]
    assert "array" in (cfg.system_instruction or "").lower()


def test_merchant_product_instructions_include_preferred_merchant():
    pref = [
        PreferredMerchantContext(name="Jumbo", website="https://www.jumbo.cl/"),
    ]
    single = merchant_product_single_system_instruction(preferred=pref)
    assert "Jumbo" in single
    assert "jumbo.cl" in single
    find = merchant_product_find_system_instruction(preferred=pref)
    assert "Jumbo" in find
    assert "JSON array" in find


def test_running_low_instruction_appends_preferred_merchants():
    base = running_low_instruction_with_merchants(preferred=None)
    assert base == gemini_service.RUNNING_LOW_SYSTEM_INSTRUCTION
    extended = running_low_instruction_with_merchants(
        preferred=[
            PreferredMerchantContext(name="Lider", website="https://www.lider.cl/"),
        ],
    )
    assert extended.startswith(gemini_service.RUNNING_LOW_SYSTEM_INSTRUCTION)
    assert "Lider" in extended
    assert "lider.cl" in extended


def test_parse_running_low_suggestions_array():
    raw = (
        '[{"product_name": "Leche", "reason": "Consumo frecuente.", "urgency": "high"}, '
        '{"product_name": "Pan", "reason": "Ya pasaron días.", "urgency": "invalid"}]'
    )
    out = _parse_running_low_suggestions(raw, max_items=10)
    assert out == [
        RunningLowSuggestion(
            product_name="Leche",
            reason="Consumo frecuente.",
            urgency="high",
        ),
        RunningLowSuggestion(
            product_name="Pan",
            reason="Ya pasaron días.",
            urgency="medium",
        ),
    ]


def test_parse_running_low_suggestions_maps_legacy_spanish_urgency():
    raw = (
        '[{"product_name": "X", "reason": "Y.", "urgency": "alta"}, '
        '{"product_name": "Z", "reason": "W.", "urgency": "baja"}]'
    )
    out = _parse_running_low_suggestions(raw, max_items=10)
    assert [x.urgency for x in out] == ["high", "low"]


@patch("groceries.gemini_service._get_client")
def test_suggest_running_low_from_purchase_history(mock_get_client):
    mock_response = MagicMock()
    mock_response.text = (
        '[{"product_name": "Arroz", "reason": "Base de comidas.", "urgency": "low"}]'
    )
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response
    mock_get_client.return_value = mock_client

    out = gemini_service.suggest_running_low_from_purchase_history(
        history_markdown="## Basket 1\n- Arroz 1 kg",
    )
    assert len(out) == 1
    assert out[0].product_name == "Arroz"
    mock_client.models.generate_content.assert_called_once()
    cfg = mock_client.models.generate_content.call_args.kwargs["config"]
    assert cfg.tools is None
