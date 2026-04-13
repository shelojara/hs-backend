from datetime import datetime

from ninja import Schema

from pagechecker import models as pc_models


class SnapshotHighlight(Schema):
    label: str
    value: str


class SnapshotContentInsights(Schema):
    about: str = ""
    page_kind: str = ""
    highlights: list[SnapshotHighlight] = []


class Snapshot(Schema):
    id: int
    created_at: datetime
    content: str
    features: list[str] = []
    content_insights: SnapshotContentInsights | None = None


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


def snapshot_from_model(s: pc_models.Snapshot) -> Snapshot:
    raw_insights = s.content_insights or {}
    insights: SnapshotContentInsights | None = None
    if isinstance(raw_insights, dict) and raw_insights:
        hl_raw = raw_insights.get("highlights") or []
        highlights: list[SnapshotHighlight] = []
        if isinstance(hl_raw, list):
            for item in hl_raw:
                if len(highlights) >= 3:
                    break
                if isinstance(item, dict) and isinstance(item.get("label"), str):
                    val = item.get("value")
                    highlights.append(
                        SnapshotHighlight(
                            label=item["label"],
                            value=val.strip()
                            if isinstance(val, str)
                            else "",
                        )
                    )
        about = raw_insights.get("about")
        page_kind = raw_insights.get("page_kind")
        insights = SnapshotContentInsights(
            about=about.strip() if isinstance(about, str) else "",
            page_kind=page_kind.strip() if isinstance(page_kind, str) else "",
            highlights=highlights,
        )
    return Snapshot(
        id=s.id,
        created_at=s.created_at,
        content=s.content,
        features=list(s.features or []),
        content_insights=insights,
    )


def page_from_model(p: pc_models.Page) -> Page:
    latest = p.latest_snapshot
    return Page(
        id=p.id,
        url=p.url,
        title=p.title,
        icon=p.icon,
        created_at=p.created_at,
        last_checked_at=p.last_checked_at,
        latest_snapshot=snapshot_from_model(latest) if latest else None,
    )
