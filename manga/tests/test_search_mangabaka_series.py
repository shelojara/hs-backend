"""``search_mangabaka_series`` service (mocked MangaBaka HTTP)."""

from unittest.mock import patch

import pytest

from manga.services import search_mangabaka_series


def test_search_mangabaka_series_returns_normalized_hits():
    raw = [
        {"id": 1, "title": "One Piece"},
        {"id": "2", "title": "Two"},
        {"id": "bad", "title": "Skip"},
        {"not": "dict"},
        {"id": 3, "title": ""},
    ]
    with patch("manga.services.search_series", return_value=(raw, {"page": 1})):
        hits, pag = search_mangabaka_series(query="  pirate  ", limit=10, page=1)
    assert hits == [
        {"mangabaka_series_id": 1, "title": "One Piece"},
        {"mangabaka_series_id": 2, "title": "Two"},
    ]
    assert pag == {"page": 1}


def test_search_mangabaka_series_clamps_limit_and_page():
    with patch("manga.services.search_series") as mock_search:
        mock_search.return_value = ([], None)
        search_mangabaka_series(query="x", limit=500, page=0)
    mock_search.assert_called_once_with(query="x", limit=25, page=1)


def test_search_mangabaka_series_empty_query_raises():
    with pytest.raises(ValueError, match="non-empty"):
        search_mangabaka_series(query="   ", limit=10, page=1)
