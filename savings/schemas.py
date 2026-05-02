from datetime import datetime
from decimal import Decimal
from typing import Optional

from ninja import Schema
from pydantic import ConfigDict, Field, field_validator, model_validator

from savings.models import AssetState, SavingsScope


class PingSavingsRequest(Schema):
    """Empty body for RPC transport consistency."""

    pass


class PingSavingsResponse(Schema):
    ok: bool = True


class CreateAssetRequest(Schema):
    scope: str
    name: str
    weight: Decimal = Field(default=Decimal("1"), gt=0)
    current_amount: Decimal = Field(default=Decimal("0"), ge=0)
    target_amount: Optional[Decimal] = Field(default=None, ge=0)
    currency: str = "CLP"

    @field_validator("name", mode="before")
    @classmethod
    def validate_name(cls, v: object) -> str:
        if not isinstance(v, str):
            msg = "Asset name must be a string."
            raise TypeError(msg)
        s = v.strip()
        if not s:
            msg = "Asset name is required."
            raise ValueError(msg)
        if len(s) > 255:
            msg = "Asset name is too long."
            raise ValueError(msg)
        return s

    @field_validator("scope", mode="before")
    @classmethod
    def validate_scope(cls, v: object) -> str:
        if not isinstance(v, str):
            msg = "scope must be a string."
            raise TypeError(msg)
        s = v.strip().upper()
        if s not in (SavingsScope.PERSONAL, SavingsScope.FAMILY):
            msg = "Invalid scope; use PERSONAL or FAMILY."
            raise ValueError(msg)
        return s

    @field_validator("currency", mode="before")
    @classmethod
    def validate_currency(cls, v: object) -> str:
        if not isinstance(v, str):
            msg = "currency must be a string."
            raise TypeError(msg)
        cur = v.strip().upper()
        if len(cur) != 3:
            msg = "currency must be a 3-letter ISO 4217 code."
            raise ValueError(msg)
        return cur


class CreateAssetResponse(Schema):
    asset_id: int


class CreateDistributionRequest(Schema):
    scope: str
    budget_amount: Decimal
    currency: str = "CLP"
    asset_ids: list[int]
    notes: str = ""

    @field_validator("notes", mode="before")
    @classmethod
    def validate_notes(cls, v: object) -> str:
        if v is None:
            return ""
        if not isinstance(v, str):
            msg = "notes must be a string."
            raise TypeError(msg)
        return v

    @field_validator("scope", mode="before")
    @classmethod
    def validate_scope(cls, v: object) -> str:
        if not isinstance(v, str):
            msg = "scope must be a string."
            raise TypeError(msg)
        s = v.strip().upper()
        if s not in (SavingsScope.PERSONAL, SavingsScope.FAMILY):
            msg = "Invalid scope; use PERSONAL or FAMILY."
            raise ValueError(msg)
        return s

    @field_validator("currency", mode="before")
    @classmethod
    def validate_currency(cls, v: object) -> str:
        if not isinstance(v, str):
            msg = "currency must be a string."
            raise TypeError(msg)
        cur = v.strip().upper()
        if len(cur) != 3:
            msg = "currency must be a 3-letter ISO 4217 code."
            raise ValueError(msg)
        return cur

    @model_validator(mode="after")
    def clp_budget_whole(self) -> "CreateDistributionRequest":
        if self.currency == "CLP":
            q = self.budget_amount.quantize(Decimal("1"))
            if self.budget_amount != q:
                msg = "CLP budget_amount must be a whole number (no decimals)."
                raise ValueError(msg)
        return self


class CreateDistributionResponse(Schema):
    distribution_id: int


class SimulateDistributionRequest(CreateDistributionRequest):
    """Same shape as create; preview splits only (no persistence)."""


class SimulatedDistributionLineSchema(Schema):
    asset_id: int
    allocated_amount: Decimal


class SimulateDistributionResponse(Schema):
    lines: list[SimulatedDistributionLineSchema]


class UpdateDistributionNotesRequest(Schema):
    distribution_id: int
    notes: str = ""

    @field_validator("notes", mode="before")
    @classmethod
    def validate_notes(cls, v: object) -> str:
        if v is None:
            return ""
        if not isinstance(v, str):
            msg = "notes must be a string."
            raise TypeError(msg)
        return v


class UpdateDistributionNotesResponse(Schema):
    distribution_id: int


class ListAssetsRequest(Schema):
    scope: str
    state: str | None = None

    @field_validator("scope", mode="before")
    @classmethod
    def validate_scope(cls, v: object) -> str:
        if not isinstance(v, str):
            msg = "scope must be a string."
            raise TypeError(msg)
        s = v.strip().upper()
        if s not in (SavingsScope.PERSONAL, SavingsScope.FAMILY):
            msg = "Invalid scope; use PERSONAL or FAMILY."
            raise ValueError(msg)
        return s

    @field_validator("state", mode="before")
    @classmethod
    def validate_state(cls, v: object) -> str | None:
        if v is None:
            return None
        if not isinstance(v, str):
            msg = "state must be a string."
            raise TypeError(msg)
        s = v.strip().upper()
        if s not in (AssetState.ACTIVE, AssetState.COMPLETED):
            msg = "Invalid state; use ACTIVE or COMPLETED."
            raise ValueError(msg)
        return s


class AssetSchema(Schema):
    model_config = ConfigDict(from_attributes=True)

    id: int
    owner_id: int
    scope: str
    family_id: int | None
    name: str
    weight: Decimal
    current_amount: Decimal
    target_amount: Optional[Decimal]
    currency: str
    emoji: str
    state: str
    completed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class ListAssetsResponse(Schema):
    assets: list[AssetSchema]


class ListDistributionsRequest(Schema):
    scope: str
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)

    @field_validator("scope", mode="before")
    @classmethod
    def validate_scope(cls, v: object) -> str:
        if not isinstance(v, str):
            msg = "scope must be a string."
            raise TypeError(msg)
        s = v.strip().upper()
        if s not in (SavingsScope.PERSONAL, SavingsScope.FAMILY):
            msg = "Invalid scope; use PERSONAL or FAMILY."
            raise ValueError(msg)
        return s


class DistributionLineSchema(Schema):
    model_config = ConfigDict(from_attributes=True)

    id: int
    asset_id: int
    allocated_amount: Decimal


class DistributionWithLinesSchema(Schema):
    model_config = ConfigDict(from_attributes=True)

    id: int
    owner_id: int
    scope: str
    family_id: int | None
    budget_amount: Decimal
    currency: str
    notes: str
    created_at: datetime
    lines: list[DistributionLineSchema]


class ListDistributionsResponse(Schema):
    distributions: list[DistributionWithLinesSchema]


class GetStatisticsRequest(Schema):
    scope: str

    @field_validator("scope", mode="before")
    @classmethod
    def validate_scope(cls, v: object) -> str:
        if not isinstance(v, str):
            msg = "scope must be a string."
            raise TypeError(msg)
        s = v.strip().upper()
        if s not in (SavingsScope.PERSONAL, SavingsScope.FAMILY):
            msg = "Invalid scope; use PERSONAL or FAMILY."
            raise ValueError(msg)
        return s


class GetStatisticsResponse(Schema):
    """Scope-level rollups: current local calendar month plus lifetime completion totals.

    ``scope_overall_progress_percent``: sum(min(current, target)) / sum(target) over assets
    with positive targets; completed assets use full target; 0% when denominator is zero.
    """

    period_month_start: datetime
    period_month_end_exclusive: datetime
    distributions_count_this_month: int
    distributions_net_budget_this_month: Decimal
    positive_allocations_sum_this_month: Decimal
    targets_hit_all_time: int
    active_assets_count: int
    completed_assets_count: int
    assets_total_count: int
    scope_overall_progress_percent: Decimal


class UpdateAssetRequest(Schema):
    asset_id: int
    name: str
    weight: Decimal = Field(default=Decimal("1"), gt=0)
    current_amount: Decimal = Field(default=Decimal("0"), ge=0)
    target_amount: Optional[Decimal] = Field(default=None, ge=0)
    currency: str = "CLP"

    @field_validator("name", mode="before")
    @classmethod
    def validate_name(cls, v: object) -> str:
        if not isinstance(v, str):
            msg = "Asset name must be a string."
            raise TypeError(msg)
        s = v.strip()
        if not s:
            msg = "Asset name is required."
            raise ValueError(msg)
        if len(s) > 255:
            msg = "Asset name is too long."
            raise ValueError(msg)
        return s

    @field_validator("currency", mode="before")
    @classmethod
    def validate_currency(cls, v: object) -> str:
        if not isinstance(v, str):
            msg = "currency must be a string."
            raise TypeError(msg)
        cur = v.strip().upper()
        if len(cur) != 3:
            msg = "currency must be a 3-letter ISO 4217 code."
            raise ValueError(msg)
        return cur


class UpdateAssetResponse(Schema):
    asset: AssetSchema


class SetAssetCompletionRequest(Schema):
    asset_id: int
    completed: bool


class SetAssetCompletionResponse(Schema):
    asset_id: int


class DeleteAssetRequest(Schema):
    asset_id: int


class DeleteAssetResponse(Schema):
    ok: bool = True


class RushAssetRequest(Schema):
    asset_id: int


class SimulateRushAssetRequest(RushAssetRequest):
    """Same fields as RushAsset; server only returns planned lines (no writes)."""
