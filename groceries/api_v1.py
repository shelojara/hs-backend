from ninja import Router
from ninja.errors import HttpError

from auth.security import protected_api_auth
from groceries import services
from groceries.gemini_service import MerchantProductInfo
from groceries.schemas import (
    AddProductToBasketRequest,
    AddProductToBasketResponse,
    BasketSchema,
    DeleteProductFromBasketRequest,
    DeleteProductFromBasketResponse,
    CreateProductFromCandidateRequest,
    CreateProductFromCandidateResponse,
    CreateProductRequest,
    CreateProductResponse,
    FindProductsRequest,
    FindProductsResponse,
    GetLatestBasketRequest,
    GetLatestBasketResponse,
    ListProductsRequest,
    ListProductsResponse,
    ProductCandidateSchema,
    ProductSchema,
    PurchaseBasketRequest,
    PurchaseBasketResponse,
    RecheckProductRequest,
    RecheckProductResponse,
)
from groceries.models import Product
from groceries.services import (
    InvalidProductListCursorError,
    NoOpenBasketError,
    ProductNameConflict,
)

router = Router(auth=protected_api_auth, tags=["Groceries"])


@router.post("/v1.Groceries.FindProducts", response=FindProductsResponse)
def find_products(request, payload: FindProductsRequest):
    try:
        items = services.find_products(query=payload.query)
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc
    anchor = payload.query.strip()
    return FindProductsResponse(
        products=[
            ProductCandidateSchema(
                name=(p.display_name or anchor).strip() or anchor,
                standard_name=p.standard_name,
                brand=p.brand,
                price=p.price,
                format=p.format,
                emoji=p.emoji,
            )
            for p in items
        ],
    )


@router.post("/v1.Groceries.CreateProductFromCandidate", response=CreateProductFromCandidateResponse)
def create_product_from_candidate(request, payload: CreateProductFromCandidateRequest):
    info = MerchantProductInfo(
        display_name=payload.name,
        standard_name=payload.standard_name,
        brand=payload.brand,
        price=payload.price,
        format=payload.format,
        emoji=payload.emoji,
    )
    try:
        product_id = services.create_product_from_merchant_info(
            query_name=payload.name,
            info=info,
            is_custom=payload.is_custom,
        )
    except ProductNameConflict as exc:
        raise HttpError(409, str(exc)) from exc
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc
    return CreateProductFromCandidateResponse(product_id=product_id)


@router.post("/v1.Groceries.CreateProduct", response=CreateProductResponse)
def create_product(request, payload: CreateProductRequest):
    user = request.auth
    c = payload.candidate
    info = MerchantProductInfo(
        display_name=c.name,
        standard_name=c.standard_name,
        brand=c.brand,
        price=c.price,
        format=c.format,
        emoji=c.emoji,
    )
    try:
        product_id = services.create_product_from_merchant_info(
            query_name=c.name,
            info=info,
            is_custom=payload.is_custom,
            user_id=user.pk,
        )
    except ProductNameConflict as exc:
        raise HttpError(409, str(exc)) from exc
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc
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
            ProductSchema(
                product_id=p.pk,
                name=p.name,
                standard_name=p.standard_name,
                brand=p.brand,
                price=p.price,
                format=p.format,
                emoji=p.emoji,
                is_custom=p.is_custom,
            )
            for p in items
        ],
        next_cursor=next_cursor,
    )


@router.post("/v1.Groceries.RecheckProduct", response=RecheckProductResponse)
def recheck_product(request, payload: RecheckProductRequest):
    try:
        services.recheck_product_from_gemini(product_id=payload.product_id)
    except Product.DoesNotExist as exc:
        raise HttpError(404, "Product not found.") from exc
    except ProductNameConflict as exc:
        raise HttpError(409, str(exc)) from exc
    return RecheckProductResponse()


@router.post("/v1.Groceries.AddProductToBasket", response=AddProductToBasketResponse)
def add_product_to_basket(request, payload: AddProductToBasketRequest):
    user = request.auth
    try:
        basket = services.add_product_to_basket(
            product_id=payload.product_id,
            user_id=user.pk,
        )
    except Product.DoesNotExist as exc:
        raise HttpError(404, "Product not found.") from exc
    return AddProductToBasketResponse(basket_id=basket.pk)


@router.post("/v1.Groceries.DeleteProductFromBasket", response=DeleteProductFromBasketResponse)
def delete_product_from_basket(request, payload: DeleteProductFromBasketRequest):
    user = request.auth
    try:
        services.delete_product_from_basket(
            product_id=payload.product_id,
            user_id=user.pk,
        )
    except Product.DoesNotExist as exc:
        raise HttpError(404, "Product not found.") from exc
    except NoOpenBasketError as exc:
        raise HttpError(404, str(exc)) from exc
    return DeleteProductFromBasketResponse()


@router.post("/v1.Groceries.PurchaseBasket", response=PurchaseBasketResponse)
def purchase_basket(request, payload: PurchaseBasketRequest):
    user = request.auth
    try:
        basket = services.purchase_latest_open_basket(user_id=user.pk)
    except NoOpenBasketError as exc:
        raise HttpError(404, str(exc)) from exc
    return PurchaseBasketResponse(basket_id=basket.pk)


@router.post("/v1.Groceries.GetLatestBasket", response=GetLatestBasketResponse)
def get_latest_basket(request, payload: GetLatestBasketRequest):
    user = request.auth
    basket = services.get_latest_basket_with_products(user_id=user.pk)
    if basket is None:
        return GetLatestBasketResponse(basket=None)
    return GetLatestBasketResponse(
        basket=BasketSchema(
            basket_id=basket.pk,
            created_at=basket.created_at,
            purchased_at=basket.purchased_at,
            total_price=services.basket_total_price(basket=basket),
            products=[
                ProductSchema(
                    product_id=p.pk,
                    name=p.name,
                    standard_name=p.standard_name,
                    brand=p.brand,
                    price=p.price,
                    format=p.format,
                    emoji=p.emoji,
                    is_custom=p.is_custom,
                )
                for p in basket.products.all()
            ],
        ),
    )
