from datetime import datetime
from decimal import Decimal
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


class FindProductsRequest(Schema):
    name: Annotated[str, AfterValidator(_strip_nonempty_product_name)]


class ProductCandidateSchema(Schema):
    """Líder-oriented fields from Gemini (or client echo); not yet persisted."""

    original_name: str
    name: str
    standard_name: str
    brand: str
    price: Decimal
    format: str
    emoji: str


class FindProductsResponse(Schema):
    products: list[ProductCandidateSchema]


class CreateProductFromCandidateRequest(Schema):
    original_name: Annotated[str, AfterValidator(_strip_nonempty_product_name)]
    name: Annotated[str, AfterValidator(_strip_nonempty_product_name)]
    standard_name: str = ""
    brand: str = ""
    price: Decimal = Decimal("0")
    format: str = ""
    emoji: str = ""


class CreateProductFromCandidateResponse(Schema):
    product_id: int


class ListProductsRequest(Schema):
    limit: int = 20
    cursor: str | None = None
    search: str | None = None


class ProductSchema(Schema):
    product_id: int
    name: str
    original_name: str
    standard_name: str
    brand: str
    price: Decimal
    format: str
    emoji: str


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


class DeleteProductFromBasketRequest(Schema):
    product_id: int


class DeleteProductFromBasketResponse(Schema):
    pass


class BasketSchema(Schema):
    basket_id: int
    created_at: datetime
    purchased_at: datetime | None
    total_price: Decimal
    products: list[ProductSchema]


class GetLatestBasketRequest(Schema):
    """No fields; POST body may be `{}` for RPC transport."""


class GetLatestBasketResponse(Schema):
    basket: BasketSchema | None


class PurchaseBasketRequest(Schema):
    """No fields; POST body may be `{}` for RPC transport."""


class PurchaseBasketResponse(Schema):
    basket_id: int
