from django.core.exceptions import ObjectDoesNotExist
from ninja import Router
from ninja.errors import HttpError

from auth.security import protected_api_auth
from backend.email_services import send_email_via_gmail
from pagechecker import services
from pagechecker.services import (
    MonitoredUrlFetchError,
    MonitoredUrlNotFoundError,
    QuestionInUseError,
)
from pagechecker.models import Page
from pagechecker.schemas import (
    AssociateQuestionsWithPageRequest,
    AssociateQuestionsWithPageResponse,
    CheckPageRequest,
    CheckPageResponse,
    CompareSnapshotsRequest,
    CompareSnapshotsResponse,
    SendDailyReportsResponse,
    SendTestEmailRequest,
    SendTestEmailResponse,
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
    ChangePageUrlRequest,
    ChangePageUrlResponse,
    SetPageCategoryRequest,
    SetPageCategoryResponse,
    SetPageReportIntervalRequest,
    SetPageReportIntervalResponse,
    SetPageFeatureInstructionRequest,
    SetPageFeatureInstructionResponse,
)

router = Router(auth=protected_api_auth, tags=["PageChecker"])


@router.post("/v1.PageChecker.ListPages", response=ListPagesResponse)
def list_pages(request, payload: ListPagesRequest):
    user = request.auth
    pages = services.list_pages(
        user_id=user.pk,
        limit=payload.limit,
        offset=payload.offset,
    )
    return ListPagesResponse(pages=pages)


@router.post("/v1.PageChecker.GetPage", response=GetPageResponse)
def get_page(request, payload: GetPageRequest):
    user = request.auth
    try:
        page = services.get_page(page_id=payload.page_id, user_id=user.pk)
    except Page.DoesNotExist:
        raise HttpError(404, "Page not found.") from None
    return GetPageResponse(page=page)


@router.post("/v1.PageChecker.CreatePage", response=CreatePageResponse)
def create_page(request, payload: CreatePageRequest):
    user = request.auth
    try:
        page_id = services.create_page(url=payload.url, user_id=user.pk)
    except MonitoredUrlNotFoundError as exc:
        raise HttpError(404, str(exc)) from exc
    except MonitoredUrlFetchError as exc:
        raise HttpError(502, str(exc)) from exc
    return CreatePageResponse(page_id=page_id)


@router.post("/v1.PageChecker.CreateQuestion", response=CreateQuestionResponse)
def create_question(request, payload: CreateQuestionRequest):
    user = request.auth
    q = services.create_question(text=payload.text, user_id=user.pk)
    return CreateQuestionResponse(question_id=q.id)


@router.post("/v1.PageChecker.ListQuestions", response=ListQuestionsResponse)
def list_questions(request):
    user = request.auth
    questions = services.list_questions(user_id=user.pk)
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
    return CreateCategoryResponse(category_id=cat.id)


@router.post("/v1.PageChecker.DeleteQuestion", response=DeleteQuestionResponse)
def delete_question(request, payload: DeleteQuestionRequest):
    user = request.auth
    try:
        services.delete_question(question_id=payload.question_id, user_id=user.pk)
    except QuestionInUseError as exc:
        raise HttpError(409, str(exc)) from exc
    return DeleteQuestionResponse()


@router.post(
    "/v1.PageChecker.AssociateQuestionsWithPage",
    response=AssociateQuestionsWithPageResponse,
)
def associate_questions_with_page(request, payload: AssociateQuestionsWithPageRequest):
    user = request.auth
    try:
        services.associate_questions_with_page(
            page_id=payload.page_id,
            question_ids=payload.question_ids,
            user_id=user.pk,
        )
    except ObjectDoesNotExist:
        raise HttpError(404, "Page not found.")
    return AssociateQuestionsWithPageResponse()


@router.post("/v1.PageChecker.SetPageCategory", response=SetPageCategoryResponse)
def set_page_category(request, payload: SetPageCategoryRequest):
    user = request.auth
    try:
        services.set_page_category(
            page_id=payload.page_id,
            user_id=user.pk,
            category_id=payload.category_id,
        )
    except Page.DoesNotExist:
        raise HttpError(404, "Page not found.")
    return SetPageCategoryResponse()


@router.post(
    "/v1.PageChecker.SetPageReportInterval",
    response=SetPageReportIntervalResponse,
)
def set_page_report_interval(request, payload: SetPageReportIntervalRequest):
    user = request.auth
    try:
        services.set_page_report_interval(
            page_id=payload.page_id,
            user_id=user.pk,
            report_interval=payload.report_interval,
        )
    except Page.DoesNotExist:
        raise HttpError(404, "Page not found.")
    return SetPageReportIntervalResponse()


@router.post(
    "/v1.PageChecker.SetPageFeatureInstruction",
    response=SetPageFeatureInstructionResponse,
)
def set_page_feature_instruction(request, payload: SetPageFeatureInstructionRequest):
    user = request.auth
    try:
        services.set_page_feature_instruction(
            page_id=payload.page_id,
            user_id=user.pk,
            feature_instruction=payload.feature_instruction,
        )
    except Page.DoesNotExist:
        raise HttpError(404, "Page not found.")
    return SetPageFeatureInstructionResponse()


@router.post("/v1.PageChecker.ChangePageUrl", response=ChangePageUrlResponse)
def change_page_url(request, payload: ChangePageUrlRequest):
    user = request.auth
    try:
        services.change_page_url(
            page_id=payload.page_id,
            url=payload.url,
            user_id=user.pk,
            keep_snapshots=payload.keep_snapshots,
        )
    except Page.DoesNotExist:
        raise HttpError(404, "Page not found.")
    except MonitoredUrlNotFoundError as exc:
        raise HttpError(404, str(exc)) from exc
    except MonitoredUrlFetchError as exc:
        raise HttpError(502, str(exc)) from exc
    return ChangePageUrlResponse()


@router.post("/v1.PageChecker.DeletePage", response=DeletePageResponse)
def delete_page(request, payload: DeletePageRequest):
    user = request.auth
    services.delete_page(page_id=payload.page_id, user_id=user.pk)
    return DeletePageResponse()


@router.post("/v1.PageChecker.CheckPage", response=CheckPageResponse)
def check_page(request, payload: CheckPageRequest):
    user = request.auth
    try:
        services.get_page(page_id=payload.page_id, user_id=user.pk)
    except Page.DoesNotExist:
        raise HttpError(404, "Page not found.") from None
    try:
        has_changed = services.check_page(page_id=payload.page_id)
    except MonitoredUrlNotFoundError as exc:
        raise HttpError(404, str(exc)) from exc
    except MonitoredUrlFetchError as exc:
        raise HttpError(502, str(exc)) from exc
    return CheckPageResponse(has_changed=has_changed)


@router.post("/v1.PageChecker.CompareSnapshots", response=CompareSnapshotsResponse)
def compare_snapshots(request, payload: CompareSnapshotsRequest):
    user = request.auth
    try:
        answer = services.compare_snapshots(
            page_id=payload.page_id,
            question=payload.question,
            user_id=user.pk,
            use_html=payload.use_html,
        )
    except ObjectDoesNotExist:
        raise HttpError(404, "Page not found.")
    except ValueError as exc:
        raise HttpError(400, str(exc))
    except RuntimeError as exc:
        raise HttpError(500, str(exc))
    return CompareSnapshotsResponse(answer=answer)


@router.post("/v1.PageChecker.SendTestEmail", response=SendTestEmailResponse)
def send_test_email(request, payload: SendTestEmailRequest):
    """Temporary: sends one plain-text message via configured Gmail SMTP."""
    try:
        send_email_via_gmail(
            to_addrs=payload.to,
            subject=payload.subject,
            body=payload.body,
        )
    except ValueError as exc:
        raise HttpError(500, str(exc)) from exc
    except OSError as exc:
        raise HttpError(502, f"SMTP send failed: {exc}") from exc
    return SendTestEmailResponse()


@router.post("/v1.PageChecker.SendDailyReports", response=SendDailyReportsResponse)
def send_daily_reports(request):
    enqueued_page_ids = services.send_daily_reports()
    return SendDailyReportsResponse(enqueued_page_ids=enqueued_page_ids)
