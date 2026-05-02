from django.conf import settings
from ninja import Router
from ninja.errors import HttpError

from auth.security import protected_api_auth
from manga import services
from manga.schemas import (
    ConvertCbzRequest,
    ConvertCbzResponse,
    ListMangaDirectoriesRequest,
    ListMangaDirectoriesResponse,
    ListMangaItemsRequest,
    ListMangaItemsResponse,
    MangaItemSchema,
)

router = Router(auth=protected_api_auth, tags=["Manga"])


@router.post("/v1.Manga.ListMangaItems", response=ListMangaItemsResponse)
def list_manga_items(request, payload: ListMangaItemsRequest):
    raw = services.list_manga_items(
        manga_root=settings.MANGA_ROOT,
        path=payload.path,
    )
    return ListMangaItemsResponse(
        items=[
            MangaItemSchema(
                name=i.name,
                path=i.path,
                is_dir=i.is_dir,
                size=i.size,
                in_dropbox=i.in_dropbox,
            )
            for i in raw
        ],
    )


@router.post("/v1.Manga.ListMangaDirectories", response=ListMangaDirectoriesResponse)
def list_manga_directories(request, payload: ListMangaDirectoriesRequest):
    dirs = services.list_manga_directories(manga_root=settings.MANGA_ROOT)
    return ListMangaDirectoriesResponse(directories=dirs)


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
