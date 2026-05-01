"""Business logic for savings app."""

from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError

from savings.models import Asset, Family, FamilyMembership, SavingsScope


class AssetMutationError(Exception):
    """Domain rule violation when persisting or mutating an asset (not request shape)."""

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
