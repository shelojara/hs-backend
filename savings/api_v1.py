from ninja import Router
from ninja.errors import HttpError

from auth.security import protected_api_auth
from savings import services
from savings.schemas import (
    CreateAssetRequest,
    CreateAssetResponse,
    CreateDistributionRequest,
    CreateDistributionResponse,
    DeleteAssetRequest,
    DeleteAssetResponse,
    GetStatisticsRequest,
    GetStatisticsResponse,
    ListAssetsRequest,
    ListAssetsResponse,
    ListDistributionsRequest,
    ListDistributionsResponse,
    PingSavingsRequest,
    PingSavingsResponse,
    RushAssetRequest,
    SetAssetCompletionRequest,
    SetAssetCompletionResponse,
    SimulateDistributionRequest,
    SimulateRushAssetRequest,
    SimulateDistributionResponse,
    SimulatedDistributionLineSchema,
    UpdateAssetRequest,
    UpdateAssetResponse,
    UpdateDistributionNotesRequest,
    UpdateDistributionNotesResponse,
)
from savings.services import AssetMutationError, DistributionMutationError

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
        )
    except AssetMutationError as exc:
        raise HttpError(exc.status_code, str(exc)) from exc
    return CreateAssetResponse(asset_id=asset_id)


@router.post("/v1.Savings.CreateDistribution", response=CreateDistributionResponse)
def create_distribution(
    request, payload: CreateDistributionRequest
) -> CreateDistributionResponse:
    user = request.auth
    try:
        did = services.create_distribution(
            user_id=user.pk,
            scope=payload.scope,
            budget_amount=payload.budget_amount,
            currency=payload.currency,
            asset_ids=payload.asset_ids,
            notes=payload.notes,
        )
    except DistributionMutationError as exc:
        raise HttpError(exc.status_code, str(exc)) from exc
    return CreateDistributionResponse(distribution_id=did)


@router.post("/v1.Savings.SimulateDistribution", response=SimulateDistributionResponse)
def simulate_distribution(
    request, payload: SimulateDistributionRequest
) -> SimulateDistributionResponse:
    user = request.auth
    try:
        pairs = services.simulate_distribution(
            user_id=user.pk,
            scope=payload.scope,
            budget_amount=payload.budget_amount,
            currency=payload.currency,
            asset_ids=payload.asset_ids,
        )
    except DistributionMutationError as exc:
        raise HttpError(exc.status_code, str(exc)) from exc
    return SimulateDistributionResponse(
        lines=[
            SimulatedDistributionLineSchema(asset_id=aid, allocated_amount=amt)
            for aid, amt in pairs
        ]
    )


@router.post(
    "/v1.Savings.UpdateDistributionNotes",
    response=UpdateDistributionNotesResponse,
)
def update_distribution_notes(
    request, payload: UpdateDistributionNotesRequest
) -> UpdateDistributionNotesResponse:
    user = request.auth
    try:
        services.update_distribution_notes(
            user_id=user.pk,
            distribution_id=payload.distribution_id,
            notes=payload.notes,
        )
    except DistributionMutationError as exc:
        raise HttpError(exc.status_code, str(exc)) from exc
    return UpdateDistributionNotesResponse(
        distribution_id=payload.distribution_id,
    )


@router.post("/v1.Savings.ListAssets", response=ListAssetsResponse)
def list_assets(request, payload: ListAssetsRequest) -> ListAssetsResponse:
    user = request.auth
    rows = services.list_assets(
        user_id=user.pk,
        scope=payload.scope,
        state=payload.state,
    )
    return ListAssetsResponse(assets=rows)


@router.post("/v1.Savings.ListDistributions", response=ListDistributionsResponse)
def list_distributions(
    request, payload: ListDistributionsRequest
) -> ListDistributionsResponse:
    user = request.auth
    rows = services.list_distributions(
        user_id=user.pk,
        scope=payload.scope,
        limit=payload.limit,
        offset=payload.offset,
    )
    return ListDistributionsResponse(distributions=rows)


@router.post("/v1.Savings.GetStatistics", response=GetStatisticsResponse)
def get_statistics(request, payload: GetStatisticsRequest) -> GetStatisticsResponse:
    user = request.auth
    stats = services.get_statistics(user_id=user.pk, scope=payload.scope)
    return GetStatisticsResponse(
        period_month_start=stats.period_month_start,
        period_month_end_exclusive=stats.period_month_end_exclusive,
        distributions_count_this_month=stats.distributions_count_this_month,
        distributions_net_budget_this_month=stats.distributions_net_budget_this_month,
        positive_allocations_sum_this_month=stats.positive_allocations_sum_this_month,
        targets_hit_all_time=stats.targets_hit_all_time,
        active_assets_count=stats.active_assets_count,
        completed_assets_count=stats.completed_assets_count,
        assets_total_count=stats.assets_total_count,
        scope_overall_progress_percent=stats.scope_overall_progress_percent,
    )


@router.post("/v1.Savings.UpdateAsset", response=UpdateAssetResponse)
def update_asset(request, payload: UpdateAssetRequest) -> UpdateAssetResponse:
    user = request.auth
    try:
        row = services.update_asset(
            user_id=user.pk,
            asset_id=payload.asset_id,
            name=payload.name,
            weight=payload.weight,
            current_amount=payload.current_amount,
            target_amount=payload.target_amount,
            currency=payload.currency,
        )
    except AssetMutationError as exc:
        raise HttpError(exc.status_code, str(exc)) from exc
    return UpdateAssetResponse(asset=row)


@router.post("/v1.Savings.SetAssetCompletion", response=SetAssetCompletionResponse)
def set_asset_completion(
    request, payload: SetAssetCompletionRequest
) -> SetAssetCompletionResponse:
    user = request.auth
    try:
        row = services.set_asset_completion(
            user_id=user.pk,
            asset_id=payload.asset_id,
            completed=payload.completed,
        )
    except AssetMutationError as exc:
        raise HttpError(exc.status_code, str(exc)) from exc
    return SetAssetCompletionResponse(asset_id=row.pk)


@router.post("/v1.Savings.DeleteAsset", response=DeleteAssetResponse)
def delete_asset(request, payload: DeleteAssetRequest) -> DeleteAssetResponse:
    user = request.auth
    try:
        services.delete_asset(user_id=user.pk, asset_id=payload.asset_id)
    except AssetMutationError as exc:
        raise HttpError(exc.status_code, str(exc)) from exc
    return DeleteAssetResponse()


@router.post("/v1.Savings.SimulateRushAsset", response=SimulateDistributionResponse)
def simulate_rush_asset(
    request, payload: SimulateRushAssetRequest
) -> SimulateDistributionResponse:
    user = request.auth
    try:
        pairs = services.simulate_rush_asset(
            user_id=user.pk,
            beneficiary_asset_id=payload.asset_id,
        )
    except DistributionMutationError as exc:
        raise HttpError(exc.status_code, str(exc)) from exc
    return SimulateDistributionResponse(
        lines=[
            SimulatedDistributionLineSchema(asset_id=aid, allocated_amount=amt)
            for aid, amt in pairs
        ]
    )


@router.post("/v1.Savings.RushAsset", response=CreateDistributionResponse)
def rush_asset(request, payload: RushAssetRequest) -> CreateDistributionResponse:
    user = request.auth
    try:
        dist_id, _row = services.rush_asset(
            user_id=user.pk,
            beneficiary_asset_id=payload.asset_id,
        )
    except DistributionMutationError as exc:
        raise HttpError(exc.status_code, str(exc)) from exc
    return CreateDistributionResponse(distribution_id=dist_id)
