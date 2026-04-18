from ninja import Router
from ninja.errors import HttpError

from auth.security import protected_api_auth
from groceries import services
from groceries.schemas import CreateProductRequest, CreateProductResponse
from groceries.services import ProductNameConflict

router = Router(auth=protected_api_auth, tags=["Groceries"])


@router.post("/v1.Groceries.CreateProduct", response=CreateProductResponse)
def create_product(request, payload: CreateProductRequest):
    try:
        product_id = services.create_product(name=payload.name)
    except ProductNameConflict as exc:
        raise HttpError(409, str(exc)) from exc
    return CreateProductResponse(product_id=product_id)
