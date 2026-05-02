from typing import Literal

from ninja import Schema


class MangaFileSchema(Schema):
    name: str
    path: str
    size: int | None = None
    in_dropbox: bool = False


class ListMangaFilesRequest(Schema):
    """Directory under manga root (``""`` = root). Lists ``.cbz`` files in that folder only."""

    path: str = ""


class ListMangaFilesResponse(Schema):
    items: list[MangaFileSchema]


class ConvertCbzRequest(Schema):
    path: str
    kind: Literal["manga", "manhwa"] = "manga"


class ConvertCbzResponse(Schema):
    pass


class DownloadCbzRequest(Schema):
    path: str
