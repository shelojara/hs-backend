from typing import Literal

from ninja import Schema


class MangaItemSchema(Schema):
    name: str
    path: str
    is_dir: bool
    size: int | None = None
    in_dropbox: bool = False


class ListMangaItemsRequest(Schema):
    path: str = ""


class ListMangaItemsResponse(Schema):
    items: list[MangaItemSchema]


class ListMangaDirectoriesRequest(Schema):
    pass


class ListMangaDirectoriesResponse(Schema):
    directories: list[str]


class ConvertCbzRequest(Schema):
    path: str
    kind: Literal["manga", "manhwa"] = "manga"


class ConvertCbzResponse(Schema):
    pass
