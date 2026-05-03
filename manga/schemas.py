from datetime import datetime
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


class CreateCbzConvertJobRequest(Schema):
    item_id: int = Field(ge=1)
    kind: Literal["manga", "manhwa"] = "manga"


class CreateCbzConvertJobResponse(Schema):
    convert_job_id: int


class ListCbzConvertJobsRequest(Schema):
    """No fields; POST body may be ``{}`` for RPC transport."""


class CbzConvertJobSchema(Schema):
    convert_job_id: int
    created_at: datetime
    series_item_id: int
    kind: str
    status: str
    completed_at: datetime | None
    failure_message: str | None = None


class ListCbzConvertJobsResponse(Schema):
    jobs: list[CbzConvertJobSchema]


class GetCbzConvertJobRequest(Schema):
    convert_job_id: int


class GetCbzConvertJobResponse(Schema):
    job: CbzConvertJobSchema


class DownloadCbzRequest(Schema):
    item_id: int


class DownloadCbzPagesRequest(Schema):
    item_id: int
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=25, ge=1, le=500)
