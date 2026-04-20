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


def _strip_nonempty_query(v: str) -> str:
    s = v.strip()
    if not s:
        msg = "Query must not be empty."
        raise ValueError(msg)
    return s


def _strip_nonempty_website(v: str) -> str:
    s = v.strip()
    if not s:
        msg = "Website must not be empty."
        raise ValueError(msg)
    return s


class FindProductCandidatesRequest(Schema):
    query: Annotated[str, AfterValidator(_strip_nonempty_query)]


class ProductCandidateSchema(Schema):
    """Fields from Gemini; not yet persisted."""

    name: str
    standard_name: str
    brand: str
    price: Decimal | None = None
    format: str
    emoji: str
    merchant: str = ""
    url: str = ""


class FindProductCandidatesResponse(Schema):
    products: list[ProductCandidateSchema]


class CreateProductFromCandidateRequest(Schema):
    canditate: ProductCandidateSchema
    is_custom: bool = False


class CreateProductFromCandidateResponse(Schema):
    product_id: int


class UpdateProductRequest(Schema):
    product_id: int
    standard_name: str
    brand: str
    format: str
    price: Decimal
    emoji: str


class UpdateProductResponse(Schema):
    product_id: int


class ListProductsRequest(Schema):
    limit: int = 50
    cursor: str | None = None
    search: str | None = None


class ProductSchema(Schema):
    product_id: int
    name: str
    standard_name: str
    brand: str
    price: Decimal
    format: str
    emoji: str
    is_custom: bool
    purchase_count: int
    running_low: bool = False


class ListProductsResponse(Schema):
    products: list[ProductSchema]
    next_cursor: str | None = None


class RecheckProductPriceRequest(Schema):
    product_id: int


class RecheckProductPriceResponse(Schema):
    product_id: int


class AddProductToBasketRequest(Schema):
    product_id: int


class AddProductToBasketResponse(Schema):
    basket_id: int


class DeleteProductFromBasketRequest(Schema):
    product_id: int


class DeleteProductFromBasketResponse(Schema):
    pass


class SetProductPurchaseInBasketRequest(Schema):
    product_id: int
    purchase: bool


class SetProductPurchaseInBasketResponse(Schema):
    basket_id: int


class BasketLineSchema(Schema):
    """One row in basket; ``purchase`` False means defer to next basket at checkout."""

    purchase: bool
    product: ProductSchema


class BasketSchema(Schema):
    basket_id: int
    created_at: datetime
    purchased_at: datetime | None
    products: list[BasketLineSchema]


class GetCurrentBasketRequest(Schema):
    """No fields; POST body may be `{}` for RPC transport."""


class GetCurrentBasketResponse(Schema):
    basket: BasketSchema | None


class PurchaseBasketRequest(Schema):
    """No fields; POST body may be `{}` for RPC transport."""


class PurchaseBasketResponse(Schema):
    basket_id: int


class PurchaseSingleProductRequest(Schema):
    product_id: int


class PurchaseSingleProductResponse(Schema):
    basket_id: int


class ListPurchasedBasketsRequest(Schema):
    """No fields; POST body may be `{}` for RPC transport."""


class ListPurchasedBasketsResponse(Schema):
    baskets: list[BasketSchema]


class WhiteboardLineSchema(Schema):
    tool: str
    points: list[float]
    color: str


class SaveWhiteboardRequest(Schema):
    data: list[WhiteboardLineSchema]


class SaveWhiteboardResponse(Schema):
    pass


class GetWhiteboardRequest(Schema):
    """No fields; POST body may be `{}` for RPC transport."""


class GetWhiteboardResponse(Schema):
    data: list[WhiteboardLineSchema]


class MerchantSchema(Schema):
    merchant_id: int
    name: str
    website: str
    favicon_url: str


class ListMerchantsRequest(Schema):
    """No fields; POST body may be `{}` for RPC transport."""


class ListMerchantsResponse(Schema):
    merchants: list[MerchantSchema]


class CreateMerchantRequest(Schema):
    name: Annotated[str, AfterValidator(_strip_nonempty_product_name)]
    website: Annotated[str, AfterValidator(_strip_nonempty_website)]


class CreateMerchantResponse(Schema):
    merchant_id: int


class UpdateMerchantRequest(Schema):
    merchant_id: int
    name: Annotated[str, AfterValidator(_strip_nonempty_product_name)]
    website: Annotated[str, AfterValidator(_strip_nonempty_website)]


class UpdateMerchantResponse(Schema):
    merchant_id: int


class DeleteMerchantRequest(Schema):
    merchant_id: int


class DeleteMerchantResponse(Schema):
    pass
