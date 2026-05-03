from django.conf import settings
from django.http import FileResponse
from ninja import Router
from ninja.errors import HttpError

from auth.security import protected_api_auth
from manga import services
from manga.schemas import (
    ConvertCbzRequest,
    ConvertCbzResponse,
    DownloadCbzRequest,
    ListSeriesItemsRequest,
    ListSeriesItemsResponse,
    ListSeriesRequest,
    ListSeriesResponse,
    SeriesItemSchema,
    SeriesSchema,
)

router = Router(auth=protected_api_auth, tags=["Manga"])


@router.post("/v1.Manga.ListSeries", response=ListSeriesResponse)
def list_series(request, payload: ListSeriesRequest):
    rows = services.list_series(
        manga_root=settings.MANGA_ROOT,
        limit=payload.limit,
        offset=payload.offset,
    )
    return ListSeriesResponse(
        items=[SeriesSchema(id=r.id, name=r.name) for r in rows],
    )


@router.post("/v1.Manga.ListSeriesItems", response=ListSeriesItemsResponse)
def list_series_items(request, payload: ListSeriesItemsRequest):
    try:
        rows = services.list_series_items(
            manga_root=settings.MANGA_ROOT,
            series_id=payload.series_id,
            limit=payload.limit,
            offset=payload.offset,
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
            )
            for r in rows
        ],
    )


@router.post("/v1.Manga.ConvertCbz", response=ConvertCbzResponse)
def convert_cbz(request, payload: ConvertCbzRequest):
    try:
        services.convert_cbz(
            manga_root=settings.MANGA_ROOT,
            path=payload.path,
            kind=payload.kind,
        )
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc
    return ConvertCbzResponse()


@router.post("/v1.Manga.DownloadCbz")
def download_cbz(request, payload: DownloadCbzRequest):
    try:
        resolved = services.resolve_cbz_download(
            manga_root=settings.MANGA_ROOT,
            path=payload.path,
        )
    except ValueError as exc:
        msg = str(exc)
        if msg == "CBZ not found":
            raise HttpError(404, msg) from exc
        raise HttpError(400, msg) from exc
    return FileResponse(
        open(resolved.absolute_path, "rb"),
        as_attachment=True,
        filename=resolved.filename,
        content_type="application/vnd.comicbook+zip",
    )
