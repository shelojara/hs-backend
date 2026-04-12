from ninja import Router

from pagechecker import gemini_service, services
from pagechecker.schemas import (
    CheckPageRequest,
    CheckPageResponse,
    CompareSnapshotsRequest,
    CompareSnapshotsResponse,
    CreatePageRequest,
    CreatePageResponse,
    DeletePageRequest,
    DeletePageResponse,
    GetPageRequest,
    GetPageResponse,
    ListPagesRequest,
    ListPagesResponse,
)

router = Router()


@router.post("/v1.PageChecker.ListPages", response=ListPagesResponse)
def list_pages(request, payload: ListPagesRequest):
    pages = services.list_pages(limit=payload.limit, offset=payload.offset)
    return ListPagesResponse(pages=pages)


@router.post("/v1.PageChecker.GetPage", response=GetPageResponse)
def get_page(request, payload: GetPageRequest):
    page = services.get_page(page_id=payload.page_id)
    return GetPageResponse(page=page)


@router.post("/v1.PageChecker.CreatePage", response=CreatePageResponse)
def create_page(request, payload: CreatePageRequest):
    page = services.create_page(url=payload.url)
    return CreatePageResponse(page=page)


@router.post("/v1.PageChecker.DeletePage", response=DeletePageResponse)
def delete_page(request, payload: DeletePageRequest):
    services.delete_page(page_id=payload.page_id)
    return DeletePageResponse()


@router.post("/v1.PageChecker.CheckPage", response=CheckPageResponse)
def check_page(request, payload: CheckPageRequest):
    has_changed = services.check_page(page_id=payload.page_id)
    return CheckPageResponse(has_changed=has_changed)


@router.post("/v1.PageChecker.CompareSnapshots", response=CompareSnapshotsResponse)
def compare_snapshots(request, payload: CompareSnapshotsRequest):
    answer = gemini_service.compare_snapshots(
        snapshot_a_id=payload.snapshot_a_id,
        snapshot_b_id=payload.snapshot_b_id,
        question=payload.question,
    )
    return CompareSnapshotsResponse(answer=answer)
