from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.http import FileResponse
from ninja import Router
from ninja.errors import HttpError

from auth.security import protected_api_auth
from manga.mangabaka_client import MangaBakaAPIError
from manga import services
from manga.models import CbzConvertJob, Series
from manga.schemas import (
    ConvertCbzRequest,
    ConvertCbzResponse,
    CreateCbzConvertJobRequest,
    CreateCbzConvertJobResponse,
    CbzConvertJobSchema,
    DownloadCbzPagesRequest,
    DownloadCbzRequest,
    GetCbzConvertJobRequest,
    GetCbzConvertJobResponse,
    GetSeriesRequest,
    GetSeriesResponse,
    ListCbzConvertJobsRequest,
    ListCbzConvertJobsResponse,
    ListSeriesItemsRequest,
    ListSeriesItemsResponse,
    ListSeriesCategoriesResponse,
    ListSeriesRequest,
    ListSeriesResponse,
    RefreshSeriesInfoRequest,
    RefreshSeriesInfoResponse,
    SearchMangabakaSeriesRequest,
    SearchMangabakaSeriesResponse,
    SetSeriesMangabakaRequest,
    SetSeriesMangabakaResponse,
    SeriesInfoSchema,
    SeriesItemSchema,
    SeriesSchema,
)

router = Router(auth=protected_api_auth, tags=["Manga"])


def _series_info_schema_or_none(series: Series) -> SeriesInfoSchema | None:
    try:
        inf = series.series_info
    except ObjectDoesNotExist:
        return None
    return SeriesInfoSchema(
        mangabaka_series_id=inf.mangabaka_series_id,
        description=(inf.description or "").strip() or None,
        rating=inf.rating,
        series_type=(inf.series_type or "").strip() or None,
        synced_at=inf.synced_at,
    )


def _series_schema(series: Series) -> SeriesSchema:
    return SeriesSchema(
        id=series.id,
        name=series.name,
        item_count=series.item_count,
        category=series.category,
        cover_image_base64=series.cover_image_base64,
        cover_image_mime_type=series.cover_image_mime_type or "",
        info=_series_info_schema_or_none(series),
    )


def _cbz_convert_job_schema(j: CbzConvertJob) -> CbzConvertJobSchema:
    return CbzConvertJobSchema(
        convert_job_id=j.pk,
        created_at=j.created_at,
        series_item_id=j.series_item_id,
        kind=j.kind,
        status=j.status,
        completed_at=j.completed_at,
        failure_message=((j.failure_message or "").strip() or None),
    )


@router.post("/v1.Manga.CreateCbzConvertJob", response=CreateCbzConvertJobResponse)
def create_cbz_convert_job(request, payload: CreateCbzConvertJobRequest):
    try:
        job_id = services.create_cbz_convert_job(
            manga_root=settings.MANGA_ROOT,
            item_id=payload.item_id,
            kind=payload.kind,
            user_id=request.auth.pk,
        )
    except ValueError as exc:
        msg = str(exc)
        if msg == "Item not found":
            raise HttpError(404, msg) from exc
        raise HttpError(400, msg) from exc
    return CreateCbzConvertJobResponse(convert_job_id=job_id)


@router.post("/v1.Manga.ListCbzConvertJobs", response=ListCbzConvertJobsResponse)
def list_cbz_convert_jobs(request, payload: ListCbzConvertJobsRequest):
    try:
        rows = services.list_cbz_convert_jobs(
            manga_root=settings.MANGA_ROOT,
            series_id=payload.series_id,
            user_id=request.auth.pk,
            status=payload.status,
        )
    except ValueError as exc:
        msg = str(exc)
        if msg == "Series not found":
            raise HttpError(404, msg) from exc
        if msg == "Invalid status filter.":
            raise HttpError(400, msg) from exc
        raise HttpError(400, msg) from exc
    return ListCbzConvertJobsResponse(
        jobs=[_cbz_convert_job_schema(j) for j in rows],
    )


@router.post("/v1.Manga.GetCbzConvertJob", response=GetCbzConvertJobResponse)
def get_cbz_convert_job(request, payload: GetCbzConvertJobRequest):
    try:
        j = services.get_cbz_convert_job(
            job_id=payload.convert_job_id,
            user_id=request.auth.pk,
        )
    except CbzConvertJob.DoesNotExist as exc:
        raise HttpError(404, "Convert job not found.") from exc
    return GetCbzConvertJobResponse(job=_cbz_convert_job_schema(j))


@router.post("/v1.Manga.ListSeries", response=ListSeriesResponse)
def list_series(request, payload: ListSeriesRequest):
    try:
        rows = services.list_series(
            manga_root=settings.MANGA_ROOT,
            limit=payload.limit,
            offset=payload.offset,
            category=payload.category,
            search=payload.search,
        )
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc
    return ListSeriesResponse(items=[_series_schema(r) for r in rows])


@router.post("/v1.Manga.GetSeries", response=GetSeriesResponse)
def get_series(request, payload: GetSeriesRequest):
    try:
        row = services.get_series(
            manga_root=settings.MANGA_ROOT,
            series_id=payload.series_id,
        )
    except ValueError as exc:
        msg = str(exc)
        if msg == "Series not found":
            raise HttpError(404, msg) from exc
        raise HttpError(400, msg) from exc
    return GetSeriesResponse(series=_series_schema(row))


@router.post("/v1.Manga.SetSeriesMangabaka", response=SetSeriesMangabakaResponse)
def set_series_mangabaka(request, payload: SetSeriesMangabakaRequest):
    try:
        row = services.set_series_mangabaka_series_id(
            manga_root=settings.MANGA_ROOT,
            series_id=payload.series_id,
            mangabaka_series_id=payload.mangabaka_series_id,
        )
    except ValueError as exc:
        msg = str(exc)
        if msg == "Series not found":
            raise HttpError(404, msg) from exc
        raise HttpError(400, msg) from exc
    except MangaBakaAPIError as exc:
        raise HttpError(502, str(exc)) from exc
    return SetSeriesMangabakaResponse(series=_series_schema(row))


@router.post("/v1.Manga.RefreshSeriesInfo", response=RefreshSeriesInfoResponse)
def refresh_series_info(request, payload: RefreshSeriesInfoRequest):
    try:
        row = services.refresh_series_info_from_mangabaka(
            manga_root=settings.MANGA_ROOT,
            series_id=payload.series_id,
        )
    except ValueError as exc:
        msg = str(exc)
        if msg == "Series not found":
            raise HttpError(404, msg) from exc
        raise HttpError(400, msg) from exc
    except MangaBakaAPIError as exc:
        raise HttpError(502, str(exc)) from exc
    return RefreshSeriesInfoResponse(series_id=row.pk)


@router.post("/v1.Manga.SearchMangabakaSeries", response=SearchMangabakaSeriesResponse)
def search_mangabaka_series_rpc(request, payload: SearchMangabakaSeriesRequest):
    try:
        results = services.search_mangabaka_series(query=payload.query)
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc
    except MangaBakaAPIError as exc:
        raise HttpError(502, str(exc)) from exc
    return SearchMangabakaSeriesResponse(results=results)


@router.post("/v1.Manga.ListSeriesCategories", response=ListSeriesCategoriesResponse)
def list_series_categories(request):
    categories = services.list_distinct_series_categories(manga_root=settings.MANGA_ROOT)
    return ListSeriesCategoriesResponse(categories=categories)


@router.post("/v1.Manga.ListSeriesItems", response=ListSeriesItemsResponse)
def list_series_items(request, payload: ListSeriesItemsRequest):
    try:
        rows = services.list_series_items(
            manga_root=settings.MANGA_ROOT,
            series_id=payload.series_id,
            limit=payload.limit,
            offset=payload.offset,
            in_dropbox=payload.in_dropbox,
        )
    except ValueError as exc:
        msg = str(exc)
        if msg == "Series not found":
            raise HttpError(404, msg) from exc
        raise HttpError(400, msg) from exc
    return ListSeriesItemsResponse(
        items=[
            SeriesItemSchema(
                id=r.id,
                filename=r.filename,
                size_bytes=r.size_bytes,
                in_dropbox=r.in_dropbox,
                file_created_at=r.file_created_at,
                cover_image_base64=r.cover_image_base64,
                cover_image_mime_type=r.cover_image_mime_type or "",
            )
            for r in rows
        ],
    )


@router.post("/v1.Manga.ConvertCbz", response=ConvertCbzResponse)
def convert_cbz(request, payload: ConvertCbzRequest):
    try:
        services.convert_cbz(
            manga_root=settings.MANGA_ROOT,
            item_id=payload.item_id,
            kind=payload.kind,
        )
    except ValueError as exc:
        msg = str(exc)
        if msg == "Item not found":
            raise HttpError(404, msg) from exc
        raise HttpError(400, msg) from exc
    return ConvertCbzResponse()


@router.post("/v1.Manga.DownloadCbz")
def download_cbz(request, payload: DownloadCbzRequest):
    try:
        resolved = services.resolve_cbz_download(
            manga_root=settings.MANGA_ROOT,
            item_id=payload.item_id,
        )
    except ValueError as exc:
        msg = str(exc)
        if msg in ("CBZ not found", "Item not found"):
            raise HttpError(404, msg) from exc
        raise HttpError(400, msg) from exc
    return FileResponse(
        open(resolved.absolute_path, "rb"),
        as_attachment=True,
        filename=resolved.filename,
        content_type="application/vnd.comicbook+zip",
    )


@router.post("/v1.Manga.DownloadCbzPages")
def download_cbz_pages(request, payload: DownloadCbzPagesRequest):
    try:
        built = services.build_cbz_page_slice(
            manga_root=settings.MANGA_ROOT,
            item_id=payload.item_id,
            offset=payload.offset,
            limit=payload.limit,
        )
    except ValueError as exc:
        msg = str(exc)
        if msg in ("CBZ not found", "Item not found"):
            raise HttpError(404, msg) from exc
        raise HttpError(400, msg) from exc
    return FileResponse(
        built.content,
        as_attachment=True,
        filename=built.filename,
        content_type="application/vnd.comicbook+zip",
    )
