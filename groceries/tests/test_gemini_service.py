from decimal import Decimal
from unittest.mock import MagicMock, patch

from groceries import gemini_service
from groceries.gemini_service import (
    MerchantProductInfo,
    PreferredMerchantContext,
    RunningLowSuggestion,
    _parse_merchant_product_list_payload,
    _parse_merchant_product_payload,
    _parse_recipe_ingredient_string_list,
    _parse_running_low_suggestions,
    _parse_search_query_kind_payload,
    merchant_product_find_system_instruction,
    merchant_product_single_system_instruction,
)


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
        merchant="",
        ingredient="",
    )
    mock_client.models.generate_content.assert_called_once()
    call_kw = mock_client.models.generate_content.call_args.kwargs
    assert "Leche entera" in call_kw["contents"]
    assert "Colún" in call_kw["contents"]


@patch("groceries.gemini_service._get_client")
def test_fetch_merchant_product_info_by_identity_strips_json_fence(mock_get_client):
    mock_response = MagicMock()
    mock_response.text = """```json
{"display_name": "", "standard_name": "Arroz grano largo", "brand": "", "price": 0, "format": "500 g", "emoji": ""}
```"""
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response
    mock_get_client.return_value = mock_client

    out = gemini_service.fetch_merchant_product_info_by_identity(
        standard_name="Arroz grano largo",
        brand="",
        format="500 g",
    )
    assert out == MerchantProductInfo(
        display_name="",
        standard_name="Arroz grano largo",
        brand="",
        price=None,
        format="500 g",
        emoji="",
        merchant="",
        ingredient="",
    )


def test_parse_plain_text_without_json_returns_none():
    assert _parse_merchant_product_payload("  Solo texto.  ") is None


def test_parse_invalid_json_returns_none():
    assert _parse_merchant_product_payload("{not json") is None


def test_parse_search_query_kind_payload_valid_and_invalid():
    assert _parse_search_query_kind_payload('{"kind": "brand"}') == "brand"
    assert _parse_search_query_kind_payload('{"kind": "PRODUCT"}') == "product"
    assert _parse_search_query_kind_payload("```json\n{\"kind\": \"recipe\"}\n```") == "recipe"
    assert _parse_search_query_kind_payload('{"kind": "other"}') == ""
    assert _parse_search_query_kind_payload("") == ""


@patch("groceries.gemini_service._get_client")
def test_classify_search_query_kind_returns_parsed_value(mock_get_client):
    mock_response = MagicMock()
    mock_response.text = '{"kind": "question"}'
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response
    mock_get_client.return_value = mock_client

    assert gemini_service.classify_search_query_kind(query="  why milk  ") == "question"
    mock_client.models.generate_content.assert_called_once()


@patch("groceries.gemini_service._get_client")
def test_classify_search_query_kind_blank_query_no_client(mock_get_client):
    assert gemini_service.classify_search_query_kind(query="   ") == ""
    mock_get_client.assert_not_called()


def test_parse_merchant_product_list_payload_array():
    raw = (
        '[{"display_name": "A", "standard_name": "Sa", "brand": "", "price": 100, '
        '"format": "", "emoji": "", "merchant": "Jumbo"}, '
        '{"display_name": "B", "standard_name": "Sb", "brand": "X", "price": 0, '
        '"format": "1 L", "emoji": "🥛"}]'
    )
    out = _parse_merchant_product_list_payload(raw, max_items=10)
    assert len(out) == 2
    assert out[0].display_name == "A"
    assert out[0].merchant == "Jumbo"
    assert out[1].format == "1 L"
    assert out[1].merchant == ""
    assert out[1].price is None


def test_parse_merchant_product_list_payload_caps_max_items():
    raw = "[" + ",".join(
        '{"display_name": "P", "standard_name": "", "brand": "", "price": 0, "format": "", "emoji": ""}'
        for _ in range(12)
    )
    raw += "]"
    out = _parse_merchant_product_list_payload(raw, max_items=10)
    assert len(out) == 10


def test_parse_merchant_product_list_payload_zero_price_becomes_none():
    raw = (
        '{"display_name": "Z", "standard_name": "", "brand": "", "price": 0, '
        '"format": "", "emoji": ""}'
    )
    out = _parse_merchant_product_list_payload(raw, max_items=10)
    assert len(out) == 1
    assert out[0].price is None


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
        '"format": "", "emoji": "", "merchant": "Lider"}]'
    )
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response
    mock_get_client.return_value = mock_client

    out = gemini_service.fetch_merchant_product_candidates(query="  milk  ")
    assert len(out) == 1
    assert out[0].display_name == "One"
    assert out[0].merchant == "Lider"
    mock_client.models.generate_content.assert_called_once()
    assert (
        mock_client.models.generate_content.call_args.kwargs["model"]
        == gemini_service.GEMINI_FIND_PRODUCTS_MODEL
    )
    cfg = mock_client.models.generate_content.call_args.kwargs["config"]
    assert "array" in (cfg.system_instruction or "").lower()


@patch("groceries.gemini_service._get_client")
def test_fetch_merchant_product_candidates_includes_page_context_in_prompt(mock_get_client):
    mock_response = MagicMock()
    mock_response.text = (
        '[{"display_name": "One", "standard_name": "T", "brand": "", "price": 1, '
        '"format": "", "emoji": "", "merchant": "Lider"}]'
    )
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response
    mock_get_client.return_value = mock_client

    gemini_service.fetch_merchant_product_candidates(
        query="https://x.cl/p",
        page_context="Precio $1000",
    )
    contents = mock_client.models.generate_content.call_args.kwargs["contents"]
    assert "https://x.cl/p" in contents
    assert "page text" in contents.lower()
    assert "Precio $1000" in contents


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
    assert f"at most {gemini_service.FIND_PRODUCTS_MAX} elements" in find
    assert "Chile" in gemini_service.RECIPE_CHILE_INGREDIENT_LIST_SYSTEM_INSTRUCTION


def test_parse_recipe_ingredient_string_list_strings_and_objects():
    raw = '["Pasta", {"ingredient": "Huevos"}, "Pasta", "  "]'
    out = _parse_recipe_ingredient_string_list(raw, max_items=10)
    assert out == ["Pasta", "Huevos"]


@patch("groceries.gemini_service._get_client")
def test_fetch_recipe_common_ingredients_chile(mock_get_client):
    mock_response = MagicMock()
    mock_response.text = '["Pasta seca", {"ingredient": "Huevos"}]'
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response
    mock_get_client.return_value = mock_client

    out = gemini_service.fetch_recipe_common_ingredients_chile(
        recipe_query="  carbonara  ",
    )
    assert out == ["Pasta seca", "Huevos"]
    contents = mock_client.models.generate_content.call_args.kwargs["contents"]
    assert "carbonara" in contents
    cfg = mock_client.models.generate_content.call_args.kwargs["config"]
    assert "Chile" in (cfg.system_instruction or "")
    assert cfg.tools is None


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
            product_ids=(),
        ),
        RunningLowSuggestion(
            product_name="Pan",
            reason="Ya pasaron días.",
            urgency="medium",
            product_ids=(),
        ),
    ]


def test_parse_running_low_suggestions_maps_legacy_spanish_urgency():
    raw = (
        '[{"product_name": "X", "reason": "Y.", "urgency": "alta"}, '
        '{"product_name": "Z", "reason": "W.", "urgency": "baja"}]'
    )
    out = _parse_running_low_suggestions(raw, max_items=10)
    assert [x.urgency for x in out] == ["high", "low"]


def test_parse_running_low_suggestions_product_ids():
    raw = (
        '[{"product_name": "A", "reason": "r.", "urgency": "low", "product_ids": [1, 2]}, '
        '{"product_name": "B", "reason": "s.", "urgency": "low", "product_ids": [3.0]}]'
    )
    out = _parse_running_low_suggestions(raw, max_items=10)
    assert out[0].product_ids == (1, 2)
    assert out[1].product_ids == (3,)


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
