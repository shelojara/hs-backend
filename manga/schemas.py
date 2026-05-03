from datetime import datetime
from typing import Literal

from ninja import Schema
from pydantic import Field


class MangaFileSchema(Schema):
    name: str
    path: str
    size: int | None = None
    in_dropbox: bool = False


class ListMangaFilesRequest(Schema):
    """Directory under manga root (``""`` = root). Lists ``.cbz`` files in that folder only."""

    path: str = ""


class ListMangaFilesResponse(Schema):
    items: list[MangaFileSchema]


class SeriesSchema(Schema):
    id: int
    series_rel_path: str
    name: str
    scanned_at: datetime
    item_count: int


class ListSeriesRequest(Schema):
    limit: int = Field(default=100, ge=1, le=500)
    offset: int = Field(default=0, ge=0)


class ListSeriesResponse(Schema):
    items: list[SeriesSchema]


class ConvertCbzRequest(Schema):
    path: str
    kind: Literal["manga", "manhwa"] = "manga"


class ConvertCbzResponse(Schema):
    pass


class DownloadCbzRequest(Schema):
    path: str
