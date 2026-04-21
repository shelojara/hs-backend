from decimal import Decimal
from unittest.mock import MagicMock, patch

from groceries.gemini_service import MerchantProductInfo
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


def test_extract_snapshot_feature_empty_instruction_returns_none():
    assert (
        gemini_service.extract_snapshot_feature(
            feature_instruction="   ",
            page_url="https://x.test/",
            page_title="",
            md_content="x",
        )
        is None
    )


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
def test_extract_snapshot_feature_with_old_snapshot_labels_old_and_new(mock_get_client):
    from datetime import UTC, datetime

    mock_response = MagicMock()
    mock_response.text = "  ok  "
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response
    mock_get_client.return_value = mock_client

    old_at = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)
    new_at = datetime(2025, 1, 2, 12, 0, 0, tzinfo=UTC)
    out = gemini_service.extract_snapshot_feature(
        feature_instruction="price?",
        page_url="https://shop.example/p",
        page_title="Product",
        md_content="# New body",
        old_md_content="# Old body",
        old_snapshot_taken_at=old_at,
        new_snapshot_taken_at=new_at,
    )
    assert out == "ok"
    mock_client.models.generate_content.assert_called_once()
    prompt = mock_client.models.generate_content.call_args.kwargs["contents"]
    assert "## Older snapshot (Markdown) — previous check" in prompt
    assert "## Newer snapshot (Markdown) — this check" in prompt
    assert "# Old body" in prompt
    assert "# New body" in prompt
    assert old_at.isoformat() in prompt
    assert new_at.isoformat() in prompt


@patch("pagechecker.gemini_service._get_client")
def test_extract_snapshot_feature_normalizes_multiline(mock_get_client):
    mock_response = MagicMock()
    mock_response.text = "  First line  \n\n  Second line  \n  Third ignored  "
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response
    mock_get_client.return_value = mock_client

    out = gemini_service.extract_snapshot_feature(
        feature_instruction="What is the price?",
        page_url="https://shop.example/p",
        page_title="Product",
        md_content="# Body",
    )
    assert out == "First line\nSecond line"
    mock_client.models.generate_content.assert_called_once()
    prompt = mock_client.models.generate_content.call_args.kwargs["contents"]
    assert "What is the price?" in prompt
    assert "https://shop.example/p" in prompt
    assert "# Body" in prompt


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


@patch("groceries.gemini_service.fetch_merchant_product_candidates")
def test_search_with_google_grounding_maps_rows(mock_fetch):
    mock_fetch.return_value = [
        MerchantProductInfo(
            display_name="Milk 1L",
            standard_name="Leche",
            brand="Colún",
            price=Decimal("2590"),
            format="1 L",
            emoji="🥛",
            merchant="Lider",
        ),
    ]
    out = gemini_service.search_with_google_grounding(query="  leche  ")
    assert out == [
        {
            "merchant": "Lider",
            "display_name": "Milk 1L",
            "standard_name": "Leche",
            "brand": "Colún",
            "price": 2590,
            "format": "1 L",
            "emoji": "🥛",
        },
    ]
    mock_fetch.assert_called_once()
    assert mock_fetch.call_args.kwargs["query"] == "leche"


def test_search_with_google_grounding_empty_query():
    assert gemini_service.search_with_google_grounding(query="  ") == []
