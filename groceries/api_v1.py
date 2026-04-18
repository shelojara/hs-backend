from ninja import Router

from auth.security import protected_api_auth
from groceries import services
from groceries.schemas import CreateProductRequest, CreateProductResponse

router = Router(auth=protected_api_auth, tags=["Groceries"])


@router.post("/v1.Groceries.CreateProduct", response=CreateProductResponse)
def create_product(request, payload: CreateProductRequest):
    product_id = services.create_product(name=payload.name)
    return CreateProductResponse(product_id=product_id)
