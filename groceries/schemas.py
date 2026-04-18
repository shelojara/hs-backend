from typing import Annotated

from ninja import Schema
from pydantic import AfterValidator


def _strip_nonempty_product_name(v: str) -> str:
    s = v.strip()
    if not s:
        msg = "Product name must not be empty."
        raise ValueError(msg)
    return s


class CreateProductRequest(Schema):
    name: Annotated[str, AfterValidator(_strip_nonempty_product_name)]


class CreateProductResponse(Schema):
    product_id: int


class ListProductsRequest(Schema):
    limit: int = 20
    cursor: str | None = None
    search: str | None = None


class ProductSchema(Schema):
    product_id: int
    name: str
    original_name: str
    brand: str
    price: str
    format: str
    details: str


class ListProductsResponse(Schema):
    products: list[ProductSchema]
    next_cursor: str | None = None


class RecheckProductRequest(Schema):
    product_id: int


class RecheckProductResponse(Schema):
    pass


class AddProductToBasketRequest(Schema):
    product_id: int


class AddProductToBasketResponse(Schema):
    basket_id: int
