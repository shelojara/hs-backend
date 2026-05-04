"""SeriesInfoSchema computed fields (API payload shape)."""

from manga.schemas import SeriesInfoSchema


def test_series_info_mangabaka_url_none_without_id():
    s = SeriesInfoSchema(mangabaka_series_id=None)
    assert s.mangabaka_url is None


def test_series_info_mangabaka_url_from_id():
    s = SeriesInfoSchema(mangabaka_series_id=42)
    assert s.mangabaka_url == "https://mangabaka.org/42"
