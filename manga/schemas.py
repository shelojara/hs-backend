from typing import Literal

from ninja import Schema
from pydantic import Field


class SeriesSchema(Schema):
    id: int
    name: str
    cover_image_base64: str | None = None
    cover_image_mime_type: str = ""


class ListSeriesRequest(Schema):
    limit: int = Field(default=100, ge=1, le=500)
    offset: int = Field(default=0, ge=0)


class ListSeriesResponse(Schema):
    items: list[SeriesSchema]


class SeriesItemSchema(Schema):
    id: int
    filename: str
    size_bytes: int | None
    in_dropbox: bool


class ListSeriesItemsRequest(Schema):
    series_id: int = Field(ge=1)
    limit: int = Field(default=100, ge=1, le=500)
    offset: int = Field(default=0, ge=0)
    in_dropbox: bool | None = None


class ListSeriesItemsResponse(Schema):
    items: list[SeriesItemSchema]


class ConvertCbzRequest(Schema):
    item_id: int
    kind: Literal["manga", "manhwa"] = "manga"


class ConvertCbzResponse(Schema):
    pass


class DownloadCbzRequest(Schema):
    item_id: int


class DownloadCbzPagesRequest(Schema):
    item_id: int
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=25, ge=1, le=500)
