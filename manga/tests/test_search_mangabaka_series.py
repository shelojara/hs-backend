"""``search_mangabaka_series`` service (mocked MangaBaka HTTP)."""

from unittest.mock import patch

import pytest

from manga.services import search_mangabaka_series

_MANGABAKA_SEARCH_MAX = 20


def test_search_mangabaka_series_returns_normalized_hits_capped():
    raw = [
        {"id": i, "title": f"T{i}"}
        for i in range(1, _MANGABAKA_SEARCH_MAX + 5)
    ]
    with patch("manga.services.search_series", return_value=(raw, {"page": 1})):
        hits = search_mangabaka_series(query="  pirate  ")
    assert len(hits) == _MANGABAKA_SEARCH_MAX
    assert hits[0] == {"mangabaka_series_id": 1, "title": "T1"}
    assert hits[-1]["mangabaka_series_id"] == _MANGABAKA_SEARCH_MAX


def test_search_mangabaka_series_calls_upstream_with_fixed_limit():
    with patch("manga.services.search_series") as mock_search:
        mock_search.return_value = ([], None)
        search_mangabaka_series(query="x")
    mock_search.assert_called_once_with(
        query="x", limit=_MANGABAKA_SEARCH_MAX, page=1
    )


def test_search_mangabaka_series_empty_query_raises():
    with pytest.raises(ValueError, match="non-empty"):
        search_mangabaka_series(query="   ")
