from datetime import datetime

from ninja import Schema
from pydantic import computed_field


class Snapshot(Schema):
    id: int
    created_at: datetime
    md_content: str = ""
    features: list[str] = []

    @computed_field  # type: ignore[prop-decorator]
    @property
    def content(self) -> str:
        """Alias of md_content for backward-compatible API clients."""
        return self.md_content


class Page(Schema):
    id: int
    url: str
    title: str = ""
    icon: str = ""
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
    # If set, only pages whose *latest* snapshot includes this token in `features` are returned.
    feature: str | None = None


class ListPagesResponse(Schema):
    pages: list[Page]


class DeletePageRequest(Schema):
    page_id: int


class DeletePageResponse(Schema):
    pass


class UpdatePageRequest(Schema):
    page_id: int
    url: str
    keep_snapshots: bool = False


class UpdatePageResponse(Schema):
    page: Page


class CompareSnapshotsRequest(Schema):
    page_id: int
    question: str
    use_html: bool = False


class CompareSnapshotsResponse(Schema):
    answer: str
