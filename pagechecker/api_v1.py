from django.core.exceptions import ObjectDoesNotExist
from ninja import Router
from ninja.errors import HttpError

from pagechecker import services
from pagechecker.models import Page
from pagechecker.schemas import (
    AssociateQuestionsWithPageRequest,
    AssociateQuestionsWithPageResponse,
    CheckPageRequest,
    CheckPageResponse,
    CompareSnapshotsRequest,
    CompareSnapshotsResponse,
    CreatePageRequest,
    CreatePageResponse,
    CreateCategoryRequest,
    CreateCategoryResponse,
    CreateQuestionRequest,
    CreateQuestionResponse,
    DeleteQuestionRequest,
    DeleteQuestionResponse,
    DeletePageRequest,
    DeletePageResponse,
    GetPageRequest,
    GetPageResponse,
    ListPagesRequest,
    ListPagesResponse,
    ListCategoriesResponse,
    ListQuestionsResponse,
    UpdatePageRequest,
    UpdatePageResponse,
)

router = Router()


@router.post("/v1.PageChecker.ListPages", response=ListPagesResponse)
def list_pages(request, payload: ListPagesRequest):
    pages = services.list_pages(
        limit=payload.limit,
        offset=payload.offset,
    )
    return ListPagesResponse(pages=pages)


@router.post("/v1.PageChecker.GetPage", response=GetPageResponse)
def get_page(request, payload: GetPageRequest):
    page = services.get_page(page_id=payload.page_id)
    return GetPageResponse(page=page)


@router.post("/v1.PageChecker.CreatePage", response=CreatePageResponse)
def create_page(request, payload: CreatePageRequest):
    page_id = services.create_page(url=payload.url)
    return CreatePageResponse(page_id=page_id)


@router.post("/v1.PageChecker.CreateQuestion", response=CreateQuestionResponse)
def create_question(request, payload: CreateQuestionRequest):
    q = services.create_question(text=payload.text)
    return CreateQuestionResponse(question_id=q.id)


@router.post("/v1.PageChecker.ListQuestions", response=ListQuestionsResponse)
def list_questions(request):
    questions = services.list_questions()
    return ListQuestionsResponse(questions=questions)


@router.post("/v1.PageChecker.ListCategories", response=ListCategoriesResponse)
def list_categories(request):
    categories = services.list_categories()
    return ListCategoriesResponse(categories=categories)


@router.post("/v1.PageChecker.CreateCategory", response=CreateCategoryResponse)
def create_category(request, payload: CreateCategoryRequest):
    try:
        cat = services.create_category(name=payload.name)
    except RuntimeError as exc:
        raise HttpError(500, str(exc)) from exc
    return CreateCategoryResponse(category=cat)


@router.post("/v1.PageChecker.DeleteQuestion", response=DeleteQuestionResponse)
def delete_question(request, payload: DeleteQuestionRequest):
    services.delete_question(question_id=payload.question_id)
    return DeleteQuestionResponse()


@router.post(
    "/v1.PageChecker.AssociateQuestionsWithPage",
    response=AssociateQuestionsWithPageResponse,
)
def associate_questions_with_page(request, payload: AssociateQuestionsWithPageRequest):
    try:
        services.associate_questions_with_page(
            page_id=payload.page_id,
            question_ids=payload.question_ids,
        )
    except ObjectDoesNotExist:
        raise HttpError(404, "Page not found.")
    return AssociateQuestionsWithPageResponse()


@router.post("/v1.PageChecker.UpdatePage", response=UpdatePageResponse)
def update_page(request, payload: UpdatePageRequest):
    try:
        services.update_page(
            page_id=payload.page_id,
            url=payload.url,
            keep_snapshots=payload.keep_snapshots,
            category_id=payload.category_id,
        )
    except Page.DoesNotExist:
        raise HttpError(404, "Page not found.")
    return UpdatePageResponse()


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
