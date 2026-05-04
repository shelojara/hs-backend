from datetime import datetime
from typing import Literal

from ninja import Schema
from pydantic import Field, computed_field, field_validator


class SeriesInfoSchema(Schema):
    """MangaBaka-backed metadata when a ``SeriesInfo`` row exists."""

    mangabaka_series_id: int | None = None
    description: str | None = None
    rating: int | None = None
    series_type: str | None = None
    synced_at: datetime | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def mangabaka_url(self) -> str | None:
        if self.mangabaka_series_id is None:
            return None
        return f"https://mangabaka.org/{self.mangabaka_series_id}"


class SeriesSchema(Schema):
    id: int
    name: str
    item_count: int
    category: str = ""
    cover_image_base64: str | None = None
    cover_image_mime_type: str = ""
    info: SeriesInfoSchema | None = None


class ListSeriesRequest(Schema):
    limit: int = Field(default=100, ge=1, le=500)
    offset: int = Field(default=0, ge=0)
    category: str | None = Field(
        default=None,
        description=(
            "Omit or null for all series; non-empty string filters by parent folder name "
            "under the library root. Empty or whitespace-only values are invalid."
        ),
    )
    search: str | None = Field(
        default=None,
        description=(
            "Omit or null for no text filter; non-empty string matches display name, "
            "full series path under the library root, or category (case-insensitive substring). "
            "Empty or whitespace-only values are invalid."
        ),
    )

    @field_validator("category")
    @classmethod
    def category_non_empty_when_set(cls, v: str | None) -> str | None:
        if v is None:
            return None
        s = v.strip()
        if not s:
            raise ValueError("category must be a non-empty string when provided")
        return s

    @field_validator("search")
    @classmethod
    def search_non_empty_when_set(cls, v: str | None) -> str | None:
        if v is None:
            return None
        s = v.strip()
        if not s:
            raise ValueError("search must be a non-empty string when provided")
        return s


class ListSeriesResponse(Schema):
    items: list[SeriesSchema]


class GetSeriesRequest(Schema):
    series_id: int = Field(ge=1)


class GetSeriesResponse(Schema):
    series: SeriesSchema


class SetSeriesMangabakaRequest(Schema):
    series_id: int = Field(ge=1)
    mangabaka_series_id: int = Field(ge=1)


class SetSeriesMangabakaResponse(Schema):
    series: SeriesSchema


class RefreshSeriesInfoRequest(Schema):
    series_id: int = Field(ge=1)


class RefreshSeriesInfoResponse(Schema):
    series_id: int


class SearchMangabakaSeriesRequest(Schema):
    """Query MangaBaka series search (ids + titles for ``SetSeriesMangabaka``)."""

    query: str = Field(min_length=1, description="Search string (non-empty after trim). Up to 20 hits.")

    @field_validator("query")
    @classmethod
    def query_strip_non_empty(cls, v: str) -> str:
        s = v.strip()
        if not s:
            raise ValueError("query must be a non-empty string")
        return s


class MangabakaSearchHitSchema(Schema):
    mangabaka_series_id: int = Field(ge=1)
    title: str


class SearchMangabakaSeriesResponse(Schema):
    results: list[MangabakaSearchHitSchema]


class ListSeriesCategoriesResponse(Schema):
    categories: list[str]


class SeriesItemSchema(Schema):
    id: int
    filename: str
    size_bytes: int | None
    is_converted: bool
    is_google_drive_backed_up: bool = False
    file_created_at: datetime | None = None
    cover_image_base64: str | None = None
    cover_image_mime_type: str = ""


class ListSeriesItemsRequest(Schema):
    series_id: int = Field(ge=1)
    limit: int = Field(default=100, ge=1, le=500)
    offset: int = Field(default=0, ge=0)
    is_converted: bool | None = None


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
    """``series_id`` null/omitted: all jobs for user in library (any series)."""

    series_id: int | None = Field(default=None, ge=1)
    status: Literal["pending", "completed", "failed"] | None = None


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


class CreateGoogleDriveBackupJobRequest(Schema):
    series_id: int = Field(ge=1)


class CreateGoogleDriveBackupJobResponse(Schema):
    backup_job_ids: list[int]


class ListGoogleDriveBackupJobsRequest(Schema):
    """``series_id`` null/omitted: all backup jobs for user in library (any series)."""

    series_id: int | None = Field(default=None, ge=1)
    status: Literal["pending", "completed", "failed"] | None = None


class GoogleDriveBackupJobSchema(Schema):
    backup_job_id: int
    created_at: datetime
    series_item_id: int
    status: str
    completed_at: datetime | None
    failure_message: str | None = None
    google_drive_file_id: str | None = None


class ListGoogleDriveBackupJobsResponse(Schema):
    jobs: list[GoogleDriveBackupJobSchema]


class GetGoogleDriveBackupJobRequest(Schema):
    backup_job_id: int


class GetGoogleDriveBackupJobResponse(Schema):
    job: GoogleDriveBackupJobSchema


class DownloadCbzRequest(Schema):
    item_id: int


class DownloadCbzPagesRequest(Schema):
    item_id: int
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=25, ge=1, le=500)
