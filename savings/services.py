"""Business logic for savings app."""

from decimal import ROUND_DOWN, Decimal

from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError

from savings.models import (
    Asset,
    Distribution,
    DistributionLine,
    Family,
    FamilyMembership,
    SavingsScope,
)


class AssetMutationError(Exception):
    """Domain rule violation when persisting or mutating an asset (not request shape)."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


class DistributionMutationError(Exception):
    """Domain rule violation when creating a distribution."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def ping() -> dict[str, bool]:
    """Health check for wiring; replace with real domain as features land."""
    return {"ok": True}


def create_asset(
    *,
    user_id: int,
    scope: str,
    name: str,
    weight: Decimal,
    current_amount: Decimal,
    target_amount: Decimal | None,
    currency: str,
    family_id: int | None,
) -> int:
    """Create asset for authenticated user. Returns new asset primary key.

    Caller must pass values already validated (e.g. from ``CreateAssetRequest``).
    """
    if scope == SavingsScope.PERSONAL:
        fam = None
    else:
        try:
            fam = Family.objects.get(pk=family_id)
        except Family.DoesNotExist as exc:
            raise AssetMutationError("Family not found.", status_code=404) from exc
        if not FamilyMembership.objects.filter(
            family_id=fam.pk,
            user_id=user_id,
        ).exists():
            raise AssetMutationError(
                "Not a member of this family.",
                status_code=403,
            )

    try:
        with transaction.atomic():
            row = Asset.objects.create(
                owner_id=user_id,
                scope=scope,
                family=fam,
                name=name,
                weight=weight,
                current_amount=current_amount,
                target_amount=target_amount,
                currency=currency,
            )
    except IntegrityError as exc:
        raise AssetMutationError(
            "An asset with this name already exists in this scope.",
            status_code=409,
        ) from exc

    return row.pk


def list_assets(*, user_id: int, scope: str) -> list[Asset]:
    """List assets for the given savings scope (caller validates ``scope``)."""
    if scope == SavingsScope.PERSONAL:
        qs = Asset.objects.filter(
            owner_id=user_id,
            scope=SavingsScope.PERSONAL,
        ).order_by("name", "id")
        return list(qs)

    membership = FamilyMembership.objects.filter(user_id=user_id).first()
    if membership is None:
        return []
    fid = membership.family_id
    qs = Asset.objects.filter(
        scope=SavingsScope.FAMILY,
        family_id=fid,
    ).order_by("name", "id")
    return list(qs)


def list_distributions(*, user_id: int, scope: str) -> list[Distribution]:
    """List distributions for scope with lines prefetched (caller validates ``scope``)."""
    if scope == SavingsScope.PERSONAL:
        qs = (
            Distribution.objects.filter(
                owner_id=user_id,
                scope=SavingsScope.PERSONAL,
            )
            .prefetch_related("lines")
            .order_by("-created_at", "-id")
        )
        return list(qs)

    membership = FamilyMembership.objects.filter(user_id=user_id).first()
    if membership is None:
        return []
    qs = (
        Distribution.objects.filter(
            scope=SavingsScope.FAMILY,
            family_id=membership.family_id,
        )
        .prefetch_related("lines")
        .order_by("-created_at", "-id")
    )
    return list(qs)


def get_asset_for_user(*, user_id: int, asset_id: int) -> Asset | None:
    """Return asset row if ``user_id`` may read it (same rules as ``list_assets``)."""
    personal = Asset.objects.filter(
        pk=asset_id,
        owner_id=user_id,
        scope=SavingsScope.PERSONAL,
    ).first()
    if personal is not None:
        return personal

    membership = FamilyMembership.objects.filter(user_id=user_id).first()
    if membership is None:
        return None
    return Asset.objects.filter(
        pk=asset_id,
        scope=SavingsScope.FAMILY,
        family_id=membership.family_id,
    ).first()


def update_asset(
    *,
    user_id: int,
    asset_id: int,
    name: str,
    weight: Decimal,
    current_amount: Decimal,
    target_amount: Decimal | None,
    currency: str,
) -> Asset:
    """Update mutable fields; caller validates payload (e.g. ``UpdateAssetRequest``)."""
    row = get_asset_for_user(user_id=user_id, asset_id=asset_id)
    if row is None:
        raise AssetMutationError("Asset not found.", status_code=404)

    row.name = name
    row.weight = weight
    row.current_amount = current_amount
    row.target_amount = target_amount
    row.currency = currency

    try:
        row.save(
            update_fields=(
                "name",
                "weight",
                "current_amount",
                "target_amount",
                "currency",
                "updated_at",
            )
        )
    except IntegrityError as exc:
        raise AssetMutationError(
            "An asset with this name already exists in this scope.",
            status_code=409,
        ) from exc

    return row


def _integer_split_by_weights(total_units: int, weights: list[Decimal]) -> list[int]:
    """Split ``total_units`` across ``weights`` using Hamilton largest remainder."""
    n = len(weights)
    total_w = sum(weights, Decimal("0"))
    exact = [Decimal(total_units) * (weights[i] / total_w) for i in range(n)]
    floors = [
        int(e.quantize(Decimal("1"), rounding=ROUND_DOWN)) for e in exact
    ]
    allocated = sum(floors)
    remainder = total_units - allocated
    frac_order = sorted(
        range(n),
        key=lambda i: (exact[i] - Decimal(floors[i]), -i),
        reverse=True,
    )
    out = floors[:]
    for k in range(remainder):
        out[frac_order[k]] += 1
    return out


def _split_budget_by_weights(
    budget_amount: Decimal,
    weights: list[Decimal],
    currency: str,
) -> list[Decimal]:
    """Pro-rata split by weights. CLP: whole pesos; other ISO currencies: hundredths."""
    if not weights:
        raise DistributionMutationError(
            "At least one asset is required.",
            status_code=400,
        )
    total_w = sum(weights, Decimal("0"))
    if total_w <= 0:
        raise DistributionMutationError(
            "Combined weight of selected assets must be positive.",
            status_code=400,
        )

    sign = Decimal("1") if budget_amount >= 0 else Decimal("-1")
    abs_budget = abs(budget_amount)

    if currency == "CLP":
        if abs_budget != abs_budget.quantize(Decimal("1")):
            raise DistributionMutationError(
                "CLP amounts must be whole pesos (no decimals).",
                status_code=400,
            )
        units = int(abs_budget)
        ints = _integer_split_by_weights(units, weights)
        return [sign * Decimal(x) for x in ints]

    cents_total = int((abs_budget * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_DOWN))
    ints = _integer_split_by_weights(cents_total, weights)
    return [sign * (Decimal(x) / Decimal("100")) for x in ints]


def delete_asset(*, user_id: int, asset_id: int) -> None:
    """Delete asset if visible to user; ``PROTECT`` on distribution lines → 409."""
    row = get_asset_for_user(user_id=user_id, asset_id=asset_id)
    if row is None:
        raise AssetMutationError("Asset not found.", status_code=404)
    try:
        row.delete()
    except ProtectedError as exc:
        raise AssetMutationError(
            "Asset has distribution history and cannot be deleted.",
            status_code=409,
        ) from exc


def create_distribution(
    *,
    user_id: int,
    scope: str,
    budget_amount: Decimal,
    currency: str,
    family_id: int | None,
    asset_ids: list[int],
) -> int:
    """Persist distribution, lines, and bump asset balances. Amounts from asset weights (pro-rata)."""
    if scope == SavingsScope.PERSONAL:
        fam = None
    else:
        try:
            fam = Family.objects.get(pk=family_id)
        except Family.DoesNotExist as exc:
            raise DistributionMutationError("Family not found.", status_code=404) from exc
        if not FamilyMembership.objects.filter(
            family_id=fam.pk,
            user_id=user_id,
        ).exists():
            raise DistributionMutationError(
                "Not a member of this family.",
                status_code=403,
            )

    if not asset_ids:
        raise DistributionMutationError(
            "At least one asset is required.",
            status_code=400,
        )

    if len(asset_ids) != len(set(asset_ids)):
        raise DistributionMutationError(
            "Duplicate asset in asset_ids.",
            status_code=400,
        )

    resolved_assets: list[Asset] = []
    for asset_id in asset_ids:
        row = get_asset_for_user(user_id=user_id, asset_id=asset_id)
        if row is None:
            raise DistributionMutationError("Asset not found.", status_code=404)
        if row.scope != scope:
            raise DistributionMutationError(
                "Asset scope does not match distribution scope.",
                status_code=400,
            )
        if scope == SavingsScope.FAMILY:
            assert fam is not None
            if row.family_id != fam.pk:
                raise DistributionMutationError(
                    "Asset does not belong to this family.",
                    status_code=400,
                )
        if row.currency != currency:
            raise DistributionMutationError(
                "All assets must use the same currency as the distribution.",
                status_code=400,
            )
        resolved_assets.append(row)

    weights = [a.weight for a in resolved_assets]
    allocated_amounts = _split_budget_by_weights(budget_amount, weights, currency)

    with transaction.atomic():
        dist = Distribution.objects.create(
            owner_id=user_id,
            scope=scope,
            family=fam,
            budget_amount=budget_amount,
            currency=currency,
        )
        for asset_row, amt in zip(resolved_assets, allocated_amounts, strict=True):
            DistributionLine.objects.create(
                distribution=dist,
                asset=asset_row,
                allocated_amount=amt,
            )
            asset_row.current_amount += amt
            asset_row.save(update_fields=("current_amount", "updated_at"))

    return dist.pk
