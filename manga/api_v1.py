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
    ListMangaSeriesRequest,
    ListMangaSeriesResponse,
    ListMangaItemsRequest,
    ListMangaItemsResponse,
    MangaDirectoryNodeSchema,
    MangaItemSchema,
)

router = Router(auth=protected_api_auth, tags=["Manga"])


def _directory_node_schema(node: services.MangaDirectoryNode) -> MangaDirectoryNodeSchema:
    return MangaDirectoryNodeSchema(
        name=node.name,
        path=node.path,
        parent_name=node.parent_name,
        children=[_directory_node_schema(c) for c in node.children],
    )


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


@router.post("/v1.Manga.ListMangaSeries", response=ListMangaSeriesResponse)
def list_manga_series(request, payload: ListMangaSeriesRequest):
    tree = services.list_manga_series(manga_root=settings.MANGA_ROOT)
    return ListMangaSeriesResponse(root=_directory_node_schema(tree))


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
