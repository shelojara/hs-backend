from ninja import Router
from ninja.errors import HttpError

from auth.security import protected_api_auth
from groceries import services
from groceries.schemas import (
    CreateProductRequest,
    CreateProductResponse,
    ListProductsRequest,
    ListProductsResponse,
    ProductSummary,
)
from groceries.services import InvalidProductListCursorError, ProductNameConflict

router = Router(auth=protected_api_auth, tags=["Groceries"])


@router.post("/v1.Groceries.CreateProduct", response=CreateProductResponse)
def create_product(request, payload: CreateProductRequest):
    try:
        product_id = services.create_product(name=payload.name)
    except ProductNameConflict as exc:
        raise HttpError(409, str(exc)) from exc
    return CreateProductResponse(product_id=product_id)


@router.post("/v1.Groceries.ListProducts", response=ListProductsResponse)
def list_products(request, payload: ListProductsRequest):
    try:
        items, next_cursor = services.list_products(
            limit=payload.limit,
            cursor=payload.cursor,
            search=payload.search,
        )
    except InvalidProductListCursorError as exc:
        raise HttpError(400, str(exc)) from exc
    return ListProductsResponse(
        products=[
            ProductSummary(
                product_id=i.product_id,
                name=i.name,
            )
            for i in items
        ],
        next_cursor=next_cursor,
    )
