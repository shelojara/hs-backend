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
    ListSeriesRequest,
    ListSeriesResponse,
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
