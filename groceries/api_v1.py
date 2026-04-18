from ninja import Router
from ninja.errors import HttpError

from auth.security import protected_api_auth
from groceries import services
from groceries.schemas import (
    AddProductToBasketRequest,
    AddProductToBasketResponse,
    BasketSchema,
    DeleteProductFromBasketRequest,
    DeleteProductFromBasketResponse,
    CreateProductRequest,
    CreateProductResponse,
    GetLatestBasketRequest,
    GetLatestBasketResponse,
    ListProductsRequest,
    ListProductsResponse,
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
    basket_calculated_price_clp,
)

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
            ProductSchema(
                product_id=p.pk,
                name=p.name,
                original_name=p.original_name,
                standard_name=p.standard_name,
                brand=p.brand,
                price=p.price,
                format=p.format,
                details=p.details,
                emoji=p.emoji,
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
    products = list(basket.products.all())
    return GetLatestBasketResponse(
        basket=BasketSchema(
            basket_id=basket.pk,
            created_at=basket.created_at,
            purchased_at=basket.purchased_at,
            calculated_price_clp=basket_calculated_price_clp(products=products),
            products=[
                ProductSchema(
                    product_id=p.pk,
                    name=p.name,
                    original_name=p.original_name,
                    standard_name=p.standard_name,
                    brand=p.brand,
                    price=p.price,
                    format=p.format,
                    details=p.details,
                    emoji=p.emoji,
                )
                for p in products
            ],
        ),
    )
