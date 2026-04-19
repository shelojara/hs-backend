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


def _strip_nonempty_standard_name(v: str) -> str:
    s = v.strip()
    if not s:
        msg = "standard_name must not be empty."
        raise ValueError(msg)
    return s


def _strip_identity_field(v: str) -> str:
    return (v or "").strip()


class FindProductCandidatesRequest(Schema):
    query: Annotated[str, AfterValidator(_strip_nonempty_query)]


class ProductCandidateSchema(Schema):
    """Fields from Gemini; not yet persisted."""

    name: str
    standard_name: str
    brand: str
    price: Decimal
    format: str
    emoji: str


class FindProductCandidatesResponse(Schema):
    products: list[ProductCandidateSchema]


class CreateProductFromCandidateRequest(Schema):
    canditate: ProductCandidateSchema
    is_custom: bool = False


class CreateProductFromCandidateResponse(Schema):
    product_id: int


class ListProductsRequest(Schema):
    limit: int = 20
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


class ListProductsResponse(Schema):
    products: list[ProductSchema]
    next_cursor: str | None = None


class RecheckProductRequest(Schema):
    product_id: int


class RecheckProductResponse(Schema):
    pass


class RecheckProductPriceByIdentityRequest(Schema):
    standard_name: Annotated[str, AfterValidator(_strip_nonempty_standard_name)]
    brand: Annotated[str, AfterValidator(_strip_identity_field)] = ""
    format: Annotated[str, AfterValidator(_strip_identity_field)] = ""


class RecheckProductPriceByIdentityResponse(Schema):
    product_id: int


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


class GetCurrentBasketRequest(Schema):
    """No fields; POST body may be `{}` for RPC transport."""


class GetCurrentBasketResponse(Schema):
    basket: BasketSchema | None


class PurchaseBasketRequest(Schema):
    """No fields; POST body may be `{}` for RPC transport."""


class PurchaseBasketResponse(Schema):
    basket_id: int


class ListPurchasedBasketsRequest(Schema):
    """No fields; POST body may be `{}` for RPC transport."""


class ListPurchasedBasketsResponse(Schema):
    baskets: list[BasketSchema]


class SuggestRunningLowRequest(Schema):
    """No fields; POST body may be `{}` for RPC transport."""


class RunningLowSuggestionSchema(Schema):
    product_name: str
    reason: str
    urgency: str  # high | medium | low


class SuggestRunningLowResponse(Schema):
    suggestions: list[RunningLowSuggestionSchema]
