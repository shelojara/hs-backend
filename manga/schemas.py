from typing import Literal

from ninja import Schema
from pydantic import Field


class SeriesSchema(Schema):
    id: int
    name: str


class ListSeriesRequest(Schema):
    limit: int = Field(default=100, ge=1, le=500)
    offset: int = Field(default=0, ge=0)


class ListSeriesResponse(Schema):
    items: list[SeriesSchema]


class ConvertCbzRequest(Schema):
    item_id: int
    kind: Literal["manga", "manhwa"] = "manga"


class ConvertCbzResponse(Schema):
    pass


class DownloadCbzRequest(Schema):
    item_id: int
