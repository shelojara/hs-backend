"""Business logic for savings app."""

from decimal import Decimal

from django.db import IntegrityError, transaction

from savings.models import Asset, Family, FamilyMembership, SavingsScope


class AssetCreateError(Exception):
    """Domain rule violation when persisting an asset (not request shape)."""

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
            raise AssetCreateError("Family not found.", status_code=404) from exc
        if not FamilyMembership.objects.filter(
            family_id=fam.pk,
            user_id=user_id,
        ).exists():
            raise AssetCreateError(
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
        raise AssetCreateError(
            "An asset with this name already exists in this scope.",
            status_code=409,
        ) from exc

    return row.pk
