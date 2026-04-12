from django.core.exceptions import ObjectDoesNotExist
from ninja import Router
from ninja.errors import HttpError

from pagechecker import services
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
    UpdatePageRequest,
    UpdatePageResponse,
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


@router.post("/v1.PageChecker.UpdatePage", response=UpdatePageResponse)
def update_page(request, payload: UpdatePageRequest):
    page = services.update_page(
        page_id=payload.page_id,
        url=payload.url,
        keep_previous_snapshots=payload.keep_previous_snapshots,
    )
    return UpdatePageResponse(page=page)


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
    try:
        answer = services.compare_snapshots(
            page_id=payload.page_id,
            question=payload.question,
            use_html=payload.use_html,
        )
    except ObjectDoesNotExist:
        raise HttpError(404, "Page not found.")
    except ValueError as exc:
        raise HttpError(400, str(exc))
    except RuntimeError as exc:
        raise HttpError(500, str(exc))
    return CompareSnapshotsResponse(answer=answer)
