"""Business logic for savings app."""

from decimal import Decimal

from django.db import IntegrityError, transaction

from savings.models import Asset, Family, FamilyMembership, SavingsScope


class AssetCreateError(Exception):
    """Invalid create-asset input or business rule violation."""

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
    """Create asset for authenticated user. Returns new asset primary key."""
    cleaned = name.strip()
    if not cleaned:
        raise AssetCreateError("Asset name is required.")
    if len(cleaned) > 255:
        raise AssetCreateError("Asset name is too long.")

    if scope not in (SavingsScope.PERSONAL, SavingsScope.FAMILY):
        raise AssetCreateError("Invalid scope; use PERSONAL or FAMILY.")

    if scope == SavingsScope.PERSONAL:
        if family_id is not None:
            raise AssetCreateError("Personal assets must not set family_id.")
        fam = None
    else:
        if family_id is None:
            raise AssetCreateError("Family assets require family_id.")
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

    if weight < 0:
        raise AssetCreateError("Weight must be non-negative.")
    if current_amount < 0:
        raise AssetCreateError("current_amount must be non-negative.")
    if target_amount is not None and target_amount < 0:
        raise AssetCreateError("target_amount must be non-negative when set.")

    cur = currency.strip().upper()
    if len(cur) != 3:
        raise AssetCreateError("currency must be a 3-letter ISO 4217 code.")

    try:
        with transaction.atomic():
            row = Asset.objects.create(
                owner_id=user_id,
                scope=scope,
                family=fam,
                name=cleaned,
                weight=weight,
                current_amount=current_amount,
                target_amount=target_amount,
                currency=cur,
            )
    except IntegrityError as exc:
        raise AssetCreateError(
            "An asset with this name already exists in this scope.",
            status_code=409,
        ) from exc

    return row.pk
