"""Smoke tests for savings models (schema wiring)."""

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from savings.models import (
    Distribution,
    DistributionLine,
    Family,
    FamilyMembership,
    SavingsAsset,
    SavingsScope,
)

User = get_user_model()


@pytest.mark.django_db
def test_create_asset_distribution_and_line() -> None:
    user = User.objects.create_user(username="u1", password="x")
    asset = SavingsAsset.objects.create(
        owner=user,
        scope=SavingsScope.PERSONAL,
        name="Silla",
        weight=Decimal("10"),
        current_amount=Decimal("25500"),
        target_amount=Decimal("200000"),
    )
    distribution = Distribution.objects.create(
        owner=user,
        scope=SavingsScope.PERSONAL,
        budget_amount=Decimal("50000"),
        currency="CLP",
    )
    line = DistributionLine.objects.create(
        distribution=distribution,
        asset=asset,
        allocated_amount=Decimal("25000"),
    )
    assert line.distribution.budget_amount == Decimal("50000")
    assert asset.distribution_lines.count() == 1


@pytest.mark.django_db
def test_family_membership_and_family_scoped_asset() -> None:
    user = User.objects.create_user(username="u2", password="x")
    family = Family.objects.create(created_by=user)
    FamilyMembership.objects.create(family=family, user=user)
    asset = SavingsAsset.objects.create(
        owner=user,
        scope=SavingsScope.FAMILY,
        family=family,
        name="Yoshi",
        weight=Decimal("10"),
    )
    distribution = Distribution.objects.create(
        owner=user,
        scope=SavingsScope.FAMILY,
        family=family,
        budget_amount=Decimal("10000"),
    )
    assert asset.family_id == family.id
    assert distribution.family_id == family.id
    assert family.memberships.count() == 1
