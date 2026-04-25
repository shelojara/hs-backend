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
    CreateRecipeFromGeminiRequest,
    CreateRecipeFromGeminiResponse,
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
    DeleteRecipeRequest,
    DeleteRecipeResponse,
    CreateProductFromCandidateRequest,
    CreateProductFromCandidateResponse,
    GetCurrentBasketRequest,
    GetCurrentBasketResponse,
    GetRecipeRequest,
    GetRecipeResponse,
    GetSearchRequest,
    GetSearchResponse,
    ListMerchantsRequest,
    ListMerchantsResponse,
    ListProductsRequest,
    ListProductsResponse,
    ListPurchasedBasketsRequest,
    ListPurchasedBasketsResponse,
    ListSearchesRequest,
    ListSearchesResponse,
    ListRecipesRequest,
    ListRecipesResponse,
    MerchantSchema,
    RecipeIngredientSchema,
    RecipeSchema,
    RecipeSummarySchema,
    RecipeStepSchema,
    RetryEmptyCompletedSearchRequest,
    RetryEmptyCompletedSearchResponse,
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
    UpdateMerchantRequest,
    UpdateMerchantResponse,
    UpdateProductRequest,
    UpdateProductResponse,
    UpdateRecipeRequest,
    UpdateRecipeResponse,
)
from groceries.models import SEARCH_DEFAULT_EMOJI, Merchant, Product, Recipe, Search
from groceries.services import (
    InvalidProductListCursorError,
    InvalidRecipeListCursorError,
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
        emoji=(s.emoji or "").strip() or SEARCH_DEFAULT_EMOJI,
        status=s.status,
        completed_at=s.completed_at,
        result_candidates=services.search_result_candidates_as_product_schemas(
            s.result_candidates,
            fallback_name=s.query,
            in_catalog_check=in_catalog_check,
        ),
        recipe_id=s.recipe_id,
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


def _recipe_summary_schema(recipe: Recipe) -> RecipeSummarySchema:
    return RecipeSummarySchema(
        recipe_id=recipe.pk,
        title=recipe.title,
        notes=recipe.notes,
        created_at=recipe.created_at,
        updated_at=recipe.updated_at,
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
    in_catalog_check = services.make_user_catalog_in_catalog_check(
        user_id=request.auth.pk,
    )
    return ListSearchesResponse(
        searches=[_search_schema(s, in_catalog_check=in_catalog_check) for s in rows],
    )


@router.post("/v1.Groceries.GetSearch", response=GetSearchResponse)
def get_search(request, payload: GetSearchRequest):
    try:
        s = services.get_search(search_id=payload.search_id, user_id=request.auth.pk)
    except Search.DoesNotExist as exc:
        raise HttpError(404, "Search not found.") from exc
    in_catalog_check = services.make_user_catalog_in_catalog_check(
        user_id=request.auth.pk,
    )

    return GetSearchResponse(
        search=_search_schema(s, in_catalog_check=in_catalog_check),
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
    "/v1.Groceries.RetryEmptyCompletedSearch",
    response=RetryEmptyCompletedSearchResponse,
)
def retry_empty_completed_search(request, payload: RetryEmptyCompletedSearchRequest):
    try:
        services.retry_empty_completed_search(
            search_id=payload.search_id,
            user_id=request.auth.pk,
        )
    except Search.DoesNotExist as exc:
        raise HttpError(404, "Search not found.") from exc
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc
    return RetryEmptyCompletedSearchResponse()


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


@router.post(
    "/v1.Groceries.CreateRecipeFromGemini",
    response=CreateRecipeFromGeminiResponse,
)
def create_recipe_from_gemini(request, payload: CreateRecipeFromGeminiRequest):
    try:
        search_id = services.create_recipe_search(
            title=payload.name,
            notes=payload.notes,
            user_id=request.auth.pk,
        )
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc
    return CreateRecipeFromGeminiResponse(search_id=search_id)


@router.post("/v1.Groceries.ListRecipes", response=ListRecipesResponse)
def list_recipes(request, payload: ListRecipesRequest):
    try:
        rows, next_cursor = services.list_user_recipes(
            user_id=request.auth.pk,
            limit=payload.limit,
            cursor=payload.cursor,
        )
    except InvalidRecipeListCursorError as exc:
        raise HttpError(400, str(exc)) from exc
    return ListRecipesResponse(
        recipes=[_recipe_summary_schema(r) for r in rows],
        next_cursor=next_cursor,
    )


@router.post("/v1.Groceries.GetRecipe", response=GetRecipeResponse)
def get_recipe(request, payload: GetRecipeRequest):
    try:
        recipe = services.get_recipe(
            recipe_id=payload.recipe_id,
            user_id=request.auth.pk,
        )
    except Recipe.DoesNotExist as exc:
        raise HttpError(404, "Recipe not found.") from exc
    ing_rows = list(recipe.ingredients.all())
    catalog_flags = services.recipe_ingredient_in_catalog_flags(
        user_id=request.auth.pk,
        ingredient_names=[ing.name for ing in ing_rows],
    )
    return GetRecipeResponse(
        recipe=RecipeSchema(
            recipe_id=recipe.pk,
            title=recipe.title,
            notes=recipe.notes,
            ingredients=[
                RecipeIngredientSchema(
                    order=ing.order,
                    name=ing.name,
                    amount=ing.amount,
                    in_catalog=catalog_flags.get((ing.name or "").strip(), False),
                )
                for ing in ing_rows
            ],
            steps=[
                RecipeStepSchema(order=st.order, text=st.text)
                for st in recipe.steps.all()
            ],
        ),
    )


@router.post("/v1.Groceries.UpdateRecipe", response=UpdateRecipeResponse)
def update_recipe(request, payload: UpdateRecipeRequest):
    ing_lines = [
        row
        for _, row in sorted(
            enumerate(payload.ingredients),
            key=lambda e: (e[1].order, e[0]),
        )
    ]
    step_rows = [
        row
        for _, row in sorted(
            enumerate(payload.steps),
            key=lambda e: (e[1].order, e[0]),
        )
    ]
    try:
        recipe = services.update_recipe(
            recipe_id=payload.recipe_id,
            user_id=request.auth.pk,
            title=payload.title,
            notes=payload.notes,
            ingredient_lines=[(ing.name, ing.amount) for ing in ing_lines],
            step_texts=[st.text for st in step_rows],
        )
    except Recipe.DoesNotExist as exc:
        raise HttpError(404, "Recipe not found.") from exc
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc
    return UpdateRecipeResponse(recipe_id=recipe.pk)


@router.post("/v1.Groceries.DeleteRecipe", response=DeleteRecipeResponse)
def delete_recipe(request, payload: DeleteRecipeRequest):
    try:
        services.delete_recipe(
            recipe_id=payload.recipe_id,
            user_id=request.auth.pk,
        )
    except Recipe.DoesNotExist as exc:
        raise HttpError(404, "Recipe not found.") from exc
    return DeleteRecipeResponse()
