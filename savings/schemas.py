from datetime import datetime
from decimal import Decimal
from typing import Optional

from ninja import Schema
from pydantic import ConfigDict, Field, field_validator, model_validator

from savings.models import SavingsScope


class PingSavingsRequest(Schema):
    """Empty body for RPC transport consistency."""

    pass


class PingSavingsResponse(Schema):
    ok: bool = True


class CreateAssetRequest(Schema):
    scope: str
    name: str
    weight: Decimal = Field(default=Decimal("1"), ge=0)
    current_amount: Decimal = Field(default=Decimal("0"), ge=0)
    target_amount: Optional[Decimal] = Field(default=None, ge=0)
    currency: str = "CLP"
    family_id: int | None = None

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

    @model_validator(mode="after")
    def family_matches_scope(self) -> "CreateAssetRequest":
        if self.scope == SavingsScope.PERSONAL:
            if self.family_id is not None:
                msg = "Personal assets must not set family_id."
                raise ValueError(msg)
        elif self.family_id is None:
            msg = "Family assets require family_id."
            raise ValueError(msg)
        return self


class CreateAssetResponse(Schema):
    asset_id: int


class CreateDistributionRequest(Schema):
    scope: str
    budget_amount: Decimal
    currency: str = "CLP"
    family_id: int | None = None
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
    def family_matches_scope(self) -> "CreateDistributionRequest":
        if self.scope == SavingsScope.PERSONAL:
            if self.family_id is not None:
                msg = "Personal distributions must not set family_id."
                raise ValueError(msg)
        elif self.family_id is None:
            msg = "Family distributions require family_id."
            raise ValueError(msg)
        if self.currency == "CLP":
            q = self.budget_amount.quantize(Decimal("1"))
            if self.budget_amount != q:
                msg = "CLP budget_amount must be a whole number (no decimals)."
                raise ValueError(msg)
        return self


class CreateDistributionResponse(Schema):
    distribution_id: int


class ListAssetsRequest(Schema):
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


class UpdateAssetRequest(Schema):
    asset_id: int
    name: str
    weight: Decimal = Field(default=Decimal("1"), ge=0)
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


class DeleteAssetRequest(Schema):
    asset_id: int


class DeleteAssetResponse(Schema):
    ok: bool = True


class RushAssetRequest(Schema):
    asset_id: int
