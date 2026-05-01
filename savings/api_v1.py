from ninja import Router
from ninja.errors import HttpError

from auth.security import protected_api_auth
from savings import services
from savings.schemas import (
    CreateAssetRequest,
    CreateAssetResponse,
    ListAssetsRequest,
    ListAssetsResponse,
    PingSavingsRequest,
    PingSavingsResponse,
)
from savings.services import AssetCreateError

router = Router(auth=protected_api_auth, tags=["Savings"])


@router.post("/v1.Savings.Ping", response=PingSavingsResponse)
def ping_savings(request, payload: PingSavingsRequest) -> PingSavingsResponse:
    _ = request.auth
    return PingSavingsResponse()


@router.post("/v1.Savings.CreateAsset", response=CreateAssetResponse)
def create_asset(request, payload: CreateAssetRequest) -> CreateAssetResponse:
    user = request.auth
    try:
        asset_id = services.create_asset(
            user_id=user.pk,
            scope=payload.scope,
            name=payload.name,
            weight=payload.weight,
            current_amount=payload.current_amount,
            target_amount=payload.target_amount,
            currency=payload.currency,
            family_id=payload.family_id,
        )
    except AssetCreateError as exc:
        raise HttpError(exc.status_code, str(exc)) from exc
    return CreateAssetResponse(asset_id=asset_id)


@router.post("/v1.Savings.ListAssets", response=ListAssetsResponse)
def list_assets(request, payload: ListAssetsRequest) -> ListAssetsResponse:
    user = request.auth
    rows = services.list_assets(user_id=user.pk, scope=payload.scope)
    return ListAssetsResponse(assets=rows)
