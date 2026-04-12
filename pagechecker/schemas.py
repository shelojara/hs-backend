from datetime import datetime
from ninja import Schema


class Snapshot(Schema):
    id: int
    created_at: datetime
    content: str


class Page(Schema):
    id: int
    url: str
    created_at: datetime
    last_checked_at: datetime | None = None
    latest_snapshot: Snapshot | None = None


class CreatePageRequest(Schema):
    url: str


class CreatePageResponse(Schema):
    page: Page


class CheckPageRequest(Schema):
    page_id: int


class CheckPageResponse(Schema):
    has_changed: bool


class GetPageRequest(Schema):
    page_id: int


class GetPageResponse(Schema):
    page: Page


class ListPagesRequest(Schema):
    limit: int = 20
    offset: int = 0


class ListPagesResponse(Schema):
    pages: list[Page]


class DeletePageRequest(Schema):
    page_id: int


class DeletePageResponse(Schema):
    pass


class CompareSnapshotsRequest(Schema):
    page_id: int
    question: str


class CompareSnapshotsResponse(Schema):
    answer: str
