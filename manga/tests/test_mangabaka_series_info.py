"""MangaBaka → ``SeriesInfo`` sync (services, no real HTTP)."""

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone as django_timezone

from manga.models import Series, SeriesInfo
from manga.services import (
    _pick_mangabaka_series_id_from_search_hits,
    sync_manga_series_info_from_mangabaka,
)


@pytest.mark.django_db
def test_pick_mangabaka_series_id_respects_fuzzy_threshold(settings):
    settings.MANGABAKA_TITLE_MATCH_THRESHOLD = 90
    hits = [
        {"id": 1, "title": "Completely Different Title"},
        {"id": 99, "title": "My Manga Title"},
    ]
    assert _pick_mangabaka_series_id_from_search_hits(local_name="My Manga Title", hits=hits) == 99
    assert (
        _pick_mangabaka_series_id_from_search_hits(local_name="Other Name", hits=hits) is None
    )


@pytest.mark.django_db
def test_sync_manga_series_info_creates_seriesinfo_from_search_and_detail(settings):
    settings.MANGABAKA_INFO_SYNC_BATCH_SIZE = 5
    settings.MANGABAKA_HTTP_DELAY_SECONDS = 0
    settings.MANGABAKA_TITLE_MATCH_THRESHOLD = 80
    settings.MANGABAKA_SEARCH_LIMIT = 10
    s = Series.objects.create(
        library_root="/tmp/lib",
        series_rel_path="X",
        name="Test Series",
        item_count=0,
    )
    search_hits = [{"id": 42, "title": "Test Series"}]

    with (
        patch("manga.services.search_series", return_value=(search_hits, {})),
        patch(
            "manga.services.fetch_series_detail",
            return_value={"description": "  Hello  ", "rating": 8, "type": "manhwa"},
        ),
    ):
        n = sync_manga_series_info_from_mangabaka()
    assert n == 1
    info = SeriesInfo.objects.get(series=s)
    assert info.mangabaka_series_id == 42
    assert info.description == "Hello"
    assert info.rating == 8
    assert info.mangabaka_type == "manhwa"
    assert info.is_complete is True
    assert info.synced_at is not None


@pytest.mark.django_db
def test_sync_seriesinfo_type_empty_when_detail_omits_type(settings):
    settings.MANGABAKA_INFO_SYNC_BATCH_SIZE = 5
    settings.MANGABAKA_HTTP_DELAY_SECONDS = 0
    settings.MANGABAKA_TITLE_MATCH_THRESHOLD = 80
    s = Series.objects.create(
        library_root="/tmp/lib",
        series_rel_path="Y",
        name="No Type Field",
        item_count=0,
    )
    with (
        patch(
            "manga.services.search_series",
            return_value=([{"id": 77, "title": "No Type Field"}], {}),
        ),
        patch(
            "manga.services.fetch_series_detail",
            return_value={"description": "x", "rating": 1},
        ),
    ):
        sync_manga_series_info_from_mangabaka()
    info = SeriesInfo.objects.get(series=s)
    assert info.mangabaka_type == ""
    assert info.is_complete is True


@pytest.mark.django_db
def test_sync_skips_series_with_complete_seriesinfo(settings):
    settings.MANGABAKA_INFO_SYNC_BATCH_SIZE = 5
    settings.MANGABAKA_HTTP_DELAY_SECONDS = 0
    s = Series.objects.create(
        library_root="/tmp/lib",
        series_rel_path="A",
        name="Done",
        item_count=0,
    )
    SeriesInfo.objects.create(
        series=s,
        mangabaka_series_id=1,
        description="x",
        rating=5,
        is_complete=True,
        synced_at=None,
    )
    with (
        patch("manga.services.search_series") as mock_search,
        patch("manga.services.fetch_series_detail") as mock_detail,
    ):
        n = sync_manga_series_info_from_mangabaka()
    assert n == 0
    mock_search.assert_not_called()
    mock_detail.assert_not_called()


@pytest.mark.django_db
def test_sync_snoozes_search_when_no_title_match(settings):
    settings.MANGABAKA_INFO_SYNC_BATCH_SIZE = 5
    settings.MANGABAKA_HTTP_DELAY_SECONDS = 0
    settings.MANGABAKA_TITLE_MATCH_THRESHOLD = 99
    settings.MANGABAKA_NO_MATCH_SNOOZE_HOURS = 24
    t0 = django_timezone.now()
    s = Series.objects.create(
        library_root="/tmp/lib",
        series_rel_path="B",
        name="Local Only",
        item_count=0,
    )
    hits = [{"id": 7, "title": "Unrelated"}]
    with (
        patch("manga.services.search_series", return_value=(hits, {})),
        patch("manga.services.timezone.now", return_value=t0),
    ):
        sync_manga_series_info_from_mangabaka()
    s.refresh_from_db()
    assert not SeriesInfo.objects.filter(series=s).exists()
    assert s.mangabaka_search_snoozed_until == t0 + timedelta(hours=24)


@pytest.mark.django_db
def test_sync_skips_series_while_search_snoozed(settings):
    settings.MANGABAKA_INFO_SYNC_BATCH_SIZE = 5
    settings.MANGABAKA_HTTP_DELAY_SECONDS = 0
    t0 = django_timezone.now()
    Series.objects.create(
        library_root="/tmp/lib",
        series_rel_path="Z",
        name="Snoozed",
        item_count=0,
        mangabaka_search_snoozed_until=t0 + timedelta(hours=1),
    )
    with patch("manga.services.search_series") as mock_search:
        n = sync_manga_series_info_from_mangabaka()
    assert n == 0
    mock_search.assert_not_called()


@pytest.mark.django_db
def test_sync_retries_search_after_snooze_expires(settings):
    settings.MANGABAKA_INFO_SYNC_BATCH_SIZE = 5
    settings.MANGABAKA_HTTP_DELAY_SECONDS = 0
    settings.MANGABAKA_TITLE_MATCH_THRESHOLD = 80
    t0 = django_timezone.now()
    s = Series.objects.create(
        library_root="/tmp/lib",
        series_rel_path="R",
        name="Later Match",
        item_count=0,
        mangabaka_search_snoozed_until=t0 - timedelta(minutes=1),
    )
    t1 = t0 + timedelta(hours=25)
    with (
        patch("manga.services.search_series", return_value=([{"id": 55, "title": "Later Match"}], {})),
        patch(
            "manga.services.fetch_series_detail",
            return_value={"description": "ok", "rating": 3},
        ),
        patch("manga.services.timezone.now", return_value=t1),
    ):
        sync_manga_series_info_from_mangabaka()
    info = SeriesInfo.objects.get(series=s)
    assert info.mangabaka_series_id == 55
    assert info.is_complete is True
    assert info.description == "ok"
    s.refresh_from_db()
    assert s.mangabaka_search_snoozed_until is None


@pytest.mark.django_db
def test_sync_detail_api_error_leaves_incomplete_for_retry(settings):
    settings.MANGABAKA_INFO_SYNC_BATCH_SIZE = 5
    settings.MANGABAKA_HTTP_DELAY_SECONDS = 0
    settings.MANGABAKA_TITLE_MATCH_THRESHOLD = 80
    s = Series.objects.create(
        library_root="/tmp/lib",
        series_rel_path="C",
        name="Retry Me",
        item_count=0,
    )
    from manga.mangabaka_client import MangaBakaAPIError

    with (
        patch(
            "manga.services.search_series",
            return_value=([{"id": 100, "title": "Retry Me"}], {}),
        ),
        patch(
            "manga.services.fetch_series_detail",
            side_effect=MangaBakaAPIError("down"),
        ),
    ):
        sync_manga_series_info_from_mangabaka()
    info = SeriesInfo.objects.get(series=s)
    assert info.mangabaka_series_id == 100
    assert info.is_complete is False
    assert info.synced_at is None
