from ninja import Router
from ninja.errors import HttpError

from auth.security import protected_api_auth
from groceries import services
from groceries.schemas import (
    AddProductToBasketRequest,
    AddProductToBasketResponse,
    BasketLineSchema,
    BasketSchema,
    CreateMerchantRequest,
    CreateMerchantResponse,
    CreateSearchRequest,
    CreateSearchResponse,
    DeleteSearchRequest,
    DeleteSearchResponse,
    DeleteMerchantRequest,
    DeleteMerchantResponse,
    DeleteProductRequest,
    DeleteProductResponse,
    DeleteProductFromBasketRequest,
    DeleteProductFromBasketResponse,
    CreateProductFromCandidateRequest,
    CreateProductFromCandidateResponse,
    FindProductCandidatesRequest,
    FindProductCandidatesResponse,
    GetCurrentBasketRequest,
    GetCurrentBasketResponse,
    GetSearchRequest,
    GetSearchResponse,
    GetWhiteboardRequest,
    GetWhiteboardResponse,
    ListMerchantsRequest,
    ListMerchantsResponse,
    ListProductsRequest,
    ListProductsResponse,
    ListPurchasedBasketsRequest,
    ListPurchasedBasketsResponse,
    ListSearchesRequest,
    ListSearchesResponse,
    MerchantSchema,
    ProductCandidateSchema,
    ProductSchema,
    SearchSchema,
    PurchaseBasketRequest,
    PurchaseBasketResponse,
    PurchaseSingleProductRequest,
    PurchaseSingleProductResponse,
    SetProductPurchaseInBasketRequest,
    SetProductPurchaseInBasketResponse,
    RecheckProductPriceRequest,
    RecheckProductPriceResponse,
    SaveWhiteboardRequest,
    SaveWhiteboardResponse,
    UpdateMerchantRequest,
    UpdateMerchantResponse,
    UpdateProductRequest,
    UpdateProductResponse,
)
from groceries.models import Merchant, Product, Search
from groceries.services import (
    InvalidProductListCursorError,
    NoOpenBasketError,
)

router = Router(auth=protected_api_auth, tags=["Groceries"])


def _search_schema(
    s: Search,
    *,
    in_catalog_check: services.CatalogInCatalogCheck | None = None,
) -> SearchSchema:
    return SearchSchema(
        search_id=s.pk,
        created_at=s.created_at,
        query=s.query,
        status=s.status,
        completed_at=s.completed_at,
        parent_id=s.parent_id,
        result_candidates=services.search_result_candidates_as_product_schemas(
            s.result_candidates,
            fallback_name=s.query,
            in_catalog_check=in_catalog_check,
        ),
    )


def _product_schema(p: Product) -> ProductSchema:
    return ProductSchema(
        product_id=p.pk,
        name=p.name,
        standard_name=p.standard_name,
        brand=p.brand,
        price=p.price,
        format=p.format,
        emoji=p.emoji,
        is_custom=p.is_custom,
        purchase_count=p.purchase_count,
        running_low=p.running_low,
    )


@router.post("/v1.Groceries.CreateSearch", response=CreateSearchResponse)
def create_search(request, payload: CreateSearchRequest):
    try:
        search_id = services.create_search(
            query=payload.query,
            user_id=request.auth.pk,
        )
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc
    return CreateSearchResponse(search_id=search_id)


@router.post("/v1.Groceries.ListSearches", response=ListSearchesResponse)
def list_searches(request, payload: ListSearchesRequest):
    rows = services.list_searches(user_id=request.auth.pk)
    return ListSearchesResponse(
        searches=[_search_schema(s) for s in rows],
    )


@router.post("/v1.Groceries.GetSearch", response=GetSearchResponse)
def get_search(request, payload: GetSearchRequest):
    try:
        s = services.get_search(search_id=payload.search_id, user_id=request.auth.pk)
    except Search.DoesNotExist as exc:
        raise HttpError(404, "Search not found.") from exc
    children = services.list_direct_child_searches(s.pk, user_id=request.auth.pk)
    in_catalog_bundles = services.load_user_catalog_in_catalog_bundles(
        user_id=request.auth.pk,
    )

    def in_catalog_check(name: str, standard_name: str, brand: str) -> bool:
        return services.in_catalog_haystacks_contain(
            name=name,
            standard_name=standard_name,
            brand=brand,
            in_catalog_bundles=in_catalog_bundles,
        )

    return GetSearchResponse(
        search=_search_schema(s, in_catalog_check=in_catalog_check),
        child_searches=[
            _search_schema(c, in_catalog_check=in_catalog_check) for c in children
        ],
    )


@router.post("/v1.Groceries.DeleteSearch", response=DeleteSearchResponse)
def delete_search(request, payload: DeleteSearchRequest):
    try:
        services.delete_search(
            search_id=payload.search_id,
            user_id=request.auth.pk,
        )
    except Search.DoesNotExist as exc:
        raise HttpError(404, "Search not found.") from exc
    return DeleteSearchResponse()


@router.post(
    "/v1.Groceries.FindProductCandidates", response=FindProductCandidatesResponse
)
def find_product_candidates(request, payload: FindProductCandidatesRequest):
    try:
        items = services.find_product_candidates(
            query=payload.query,
            user_id=request.auth.pk,
        )
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
                merchant=p.merchant,
                ingredient=p.ingredient,
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


@router.post("/v1.Groceries.DeleteProduct", response=DeleteProductResponse)
def delete_product(request, payload: DeleteProductRequest):
    try:
        services.delete_product(
            product_id=payload.product_id,
            user_id=request.auth.pk,
        )
    except Product.DoesNotExist as exc:
        raise HttpError(404, "Product not found.") from exc
    return DeleteProductResponse()


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
                running_low=p.running_low,
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


@router.post(
    "/v1.Groceries.SetProductPurchaseInBasket",
    response=SetProductPurchaseInBasketResponse,
)
def set_product_purchase_in_basket(
    request,
    payload: SetProductPurchaseInBasketRequest,
):
    user = request.auth
    try:
        basket = services.set_product_purchase_in_open_basket(
            product_id=payload.product_id,
            user_id=user.pk,
            purchase=payload.purchase,
        )
    except Product.DoesNotExist as exc:
        raise HttpError(404, "Product not found.") from exc
    except NoOpenBasketError as exc:
        raise HttpError(404, str(exc)) from exc
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc
    return SetProductPurchaseInBasketResponse(basket_id=basket.pk)


@router.post("/v1.Groceries.PurchaseBasket", response=PurchaseBasketResponse)
def purchase_basket(request, payload: PurchaseBasketRequest):
    user = request.auth
    try:
        basket = services.purchase_latest_open_basket(user_id=user.pk)
    except NoOpenBasketError as exc:
        raise HttpError(404, str(exc)) from exc
    return PurchaseBasketResponse(basket_id=basket.pk)


@router.post(
    "/v1.Groceries.PurchaseSingleProduct",
    response=PurchaseSingleProductResponse,
)
def purchase_single_product(request, payload: PurchaseSingleProductRequest):
    user = request.auth
    try:
        basket = services.purchase_single_product(
            product_id=payload.product_id,
            user_id=user.pk,
        )
    except Product.DoesNotExist as exc:
        raise HttpError(404, "Product not found.") from exc
    return PurchaseSingleProductResponse(basket_id=basket.pk)


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
            products=[
                BasketLineSchema(
                    purchase=line_purchase,
                    product=_product_schema(p),
                )
                for p, line_purchase in services.basket_product_lines(
                    basket_id=basket.pk,
                )
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
                products=[
                    BasketLineSchema(
                        purchase=line_purchase,
                        product=_product_schema(p),
                    )
                    for p, line_purchase in services.basket_product_lines(
                        basket_id=basket.pk,
                    )
                ],
            )
            for basket in rows
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


@router.post("/v1.Groceries.ListMerchants", response=ListMerchantsResponse)
def list_merchants(request, payload: ListMerchantsRequest):
    rows = services.list_user_merchants(user_id=request.auth.pk)
    return ListMerchantsResponse(
        merchants=[
            MerchantSchema(
                merchant_id=m.pk,
                name=m.name,
                website=m.website,
                favicon_url=m.favicon_url,
            )
            for m in rows
        ],
    )


@router.post("/v1.Groceries.CreateMerchant", response=CreateMerchantResponse)
def create_merchant(request, payload: CreateMerchantRequest):
    try:
        m = services.create_user_merchant(
            user_id=request.auth.pk,
            name=payload.name,
            website=payload.website,
        )
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc
    return CreateMerchantResponse(merchant_id=m.pk)


@router.post("/v1.Groceries.UpdateMerchant", response=UpdateMerchantResponse)
def update_merchant(request, payload: UpdateMerchantRequest):
    try:
        m = services.update_user_merchant(
            user_id=request.auth.pk,
            merchant_id=payload.merchant_id,
            name=payload.name,
            website=payload.website,
        )
    except Merchant.DoesNotExist as exc:
        raise HttpError(404, "Merchant not found.") from exc
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc
    return UpdateMerchantResponse(merchant_id=m.pk)


@router.post("/v1.Groceries.DeleteMerchant", response=DeleteMerchantResponse)
def delete_merchant(request, payload: DeleteMerchantRequest):
    try:
        services.delete_user_merchant(
            user_id=request.auth.pk,
            merchant_id=payload.merchant_id,
        )
    except Merchant.DoesNotExist as exc:
        raise HttpError(404, "Merchant not found.") from exc
    return DeleteMerchantResponse()
