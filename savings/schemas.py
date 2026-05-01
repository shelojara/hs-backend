from decimal import Decimal
from typing import Optional

from ninja import Schema


class PingSavingsRequest(Schema):
    """Empty body for RPC transport consistency."""

    pass


class PingSavingsResponse(Schema):
    ok: bool = True


class CreateAssetRequest(Schema):
    scope: str
    name: str
    weight: Decimal = Decimal("1")
    current_amount: Decimal = Decimal("0")
    target_amount: Optional[Decimal] = None
    currency: str = "CLP"
    family_id: int | None = None


class CreateAssetResponse(Schema):
    asset_id: int
