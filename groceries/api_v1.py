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
    CreateProductFromCandidateRequest,
    CreateProductFromCandidateResponse,
    FindProductCandidatesRequest,
    FindProductCandidatesResponse,
    GetCurrentBasketRequest,
    GetCurrentBasketResponse,
    GetWhiteboardRequest,
    GetWhiteboardResponse,
    ListProductsRequest,
    ListProductsResponse,
    ListPurchasedBasketsRequest,
    ListPurchasedBasketsResponse,
    ProductCandidateSchema,
    ProductSchema,
    PurchaseBasketRequest,
    PurchaseBasketResponse,
    RecheckProductPriceRequest,
    RecheckProductPriceResponse,
    RunningLowSuggestionSchema,
    SaveWhiteboardRequest,
    SaveWhiteboardResponse,
    SuggestRunningLowRequest,
    SuggestRunningLowResponse,
    UpdateProductRequest,
    UpdateProductResponse,
)
from groceries.models import Product
from groceries.services import (
    InvalidProductListCursorError,
    NoOpenBasketError,
)

router = Router(auth=protected_api_auth, tags=["Groceries"])


@router.post(
    "/v1.Groceries.FindProductCandidates", response=FindProductCandidatesResponse
)
def find_product_candidates(request, payload: FindProductCandidatesRequest):
    try:
        items = services.find_product_candidates(query=payload.query)
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc
    return FindProductCandidatesResponse(
        products=[
            ProductCandidateSchema(
                name=(p.display_name or payload.query.strip()).strip(),
                standard_name=p.standard_name,
                brand=p.brand,
                price=p.price,
                format=p.format,
                emoji=p.emoji,
            )
            for p in items
        ],
    )


@router.post(
    "/v1.Groceries.CreateProductFromCandidate",
    response=CreateProductFromCandidateResponse,
)
def create_product_from_candidate(request, payload: CreateProductFromCandidateRequest):
    try:
        product_id = services.create_product_from_candidate(
            candidate=payload.canditate,
            is_custom=payload.is_custom,
            user_id=request.auth.pk,
        )
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc
    return CreateProductFromCandidateResponse(product_id=product_id)


@router.post("/v1.Groceries.UpdateProduct", response=UpdateProductResponse)
def update_product(request, payload: UpdateProductRequest):
    try:
        product = services.update_product(
            product_id=payload.product_id,
            user_id=request.auth.pk,
            standard_name=payload.standard_name,
            brand=payload.brand,
            format=payload.format,
            price=payload.price,
            emoji=payload.emoji,
        )
    except Product.DoesNotExist as exc:
        raise HttpError(404, "Product not found.") from exc
    return UpdateProductResponse(product_id=product.pk)


@router.post("/v1.Groceries.ListProducts", response=ListProductsResponse)
def list_products(request, payload: ListProductsRequest):
    try:
        items, next_cursor = services.list_products(
            limit=payload.limit,
            cursor=payload.cursor,
            search=payload.search,
            user_id=request.auth.pk,
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
                purchase_count=p.purchase_count,
            )
            for p in items
        ],
        next_cursor=next_cursor,
    )


@router.post("/v1.Groceries.RecheckProductPrice", response=RecheckProductPriceResponse)
def recheck_product_price(request, payload: RecheckProductPriceRequest):
    try:
        product = services.recheck_product_price(
            product_id=payload.product_id,
            user_id=request.auth.pk,
        )
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc
    except Product.DoesNotExist as exc:
        raise HttpError(404, "Product not found.") from exc
    return RecheckProductPriceResponse(product_id=product.pk)


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


@router.post(
    "/v1.Groceries.DeleteProductFromBasket", response=DeleteProductFromBasketResponse
)
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


@router.post("/v1.Groceries.GetCurrentBasket", response=GetCurrentBasketResponse)
def get_current_basket(request, payload: GetCurrentBasketRequest):
    user = request.auth
    basket = services.get_current_basket_with_products(user_id=user.pk)
    if basket is None:
        return GetCurrentBasketResponse(basket=None)
    return GetCurrentBasketResponse(
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
                    purchase_count=p.purchase_count,
                )
                for p in basket.products.all()
            ],
        ),
    )


@router.post(
    "/v1.Groceries.ListPurchasedBaskets", response=ListPurchasedBasketsResponse
)
def list_purchased_baskets(request, payload: ListPurchasedBasketsRequest):
    user = request.auth
    rows = services.list_purchased_baskets(user_id=user.pk)
    return ListPurchasedBasketsResponse(
        baskets=[
            BasketSchema(
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
                        purchase_count=p.purchase_count,
                    )
                    for p in basket.products.all()
                ],
            )
            for basket in rows
        ],
    )


@router.post("/v1.Groceries.SuggestRunningLow", response=SuggestRunningLowResponse)
def suggest_running_low(request, payload: SuggestRunningLowRequest):
    user = request.auth
    items = services.suggest_running_low_products(user_id=user.pk)
    return SuggestRunningLowResponse(
        suggestions=[
            RunningLowSuggestionSchema(
                product_name=s.product_name,
                reason=s.reason,
                urgency=s.urgency,
            )
            for s in items
        ],
    )


@router.post("/v1.Groceries.SaveWhiteboard", response=SaveWhiteboardResponse)
def save_whiteboard(request, payload: SaveWhiteboardRequest):
    services.save_whiteboard(user_id=request.auth.pk, lines=payload.data)
    return SaveWhiteboardResponse()


@router.post("/v1.Groceries.GetWhiteboard", response=GetWhiteboardResponse)
def get_whiteboard(request, payload: GetWhiteboardRequest):
    lines = services.get_whiteboard(user_id=request.auth.pk)
    return GetWhiteboardResponse(data=lines)
