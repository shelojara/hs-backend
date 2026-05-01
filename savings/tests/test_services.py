from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from savings.models import Asset, Family, FamilyMembership, SavingsScope
from savings.services import AssetCreateError, create_asset

User = get_user_model()


def _user(username: str = "u1"):
    return User.objects.create_user(username=username, password="pw")


@pytest.mark.django_db
def test_create_asset_personal():
    user = _user()
    aid = create_asset(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        name="  Emergency  ",
        weight=Decimal("2"),
        current_amount=Decimal("10.50"),
        target_amount=Decimal("100"),
        currency="clp",
        family_id=None,
    )
    row = Asset.objects.get(pk=aid)
    assert row.owner_id == user.pk
    assert row.scope == SavingsScope.PERSONAL
    assert row.family_id is None
    assert row.name == "Emergency"
    assert row.weight == Decimal("2")
    assert row.current_amount == Decimal("10.50")
    assert row.target_amount == Decimal("100")
    assert row.currency == "CLP"


@pytest.mark.django_db
def test_create_asset_null_target():
    user = _user()
    aid = create_asset(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        name="Open goal",
        weight=Decimal("1"),
        current_amount=Decimal("0"),
        target_amount=None,
        currency="CLP",
        family_id=None,
    )
    row = Asset.objects.get(pk=aid)
    assert row.target_amount is None


@pytest.mark.django_db
def test_create_asset_family_requires_membership():
    owner = _user("owner")
    other = _user("other")
    fam = Family.objects.create(created_by=owner)
    FamilyMembership.objects.create(family=fam, user=owner)

    with pytest.raises(AssetCreateError) as ei:
        create_asset(
            user_id=other.pk,
            scope=SavingsScope.FAMILY,
            name="Shared",
            weight=Decimal("1"),
            current_amount=Decimal("0"),
            target_amount=Decimal("0"),
            currency="CLP",
            family_id=fam.pk,
        )
    assert ei.value.status_code == 403


@pytest.mark.django_db
def test_create_asset_family_ok():
    user = _user()
    fam = Family.objects.create(created_by=user)
    FamilyMembership.objects.create(family=fam, user=user)

    aid = create_asset(
        user_id=user.pk,
        scope=SavingsScope.FAMILY,
        name="Vacation",
        weight=Decimal("1"),
        current_amount=Decimal("0"),
        target_amount=Decimal("500"),
        currency="USD",
        family_id=fam.pk,
    )
    row = Asset.objects.get(pk=aid)
    assert row.scope == SavingsScope.FAMILY
    assert row.family_id == fam.pk


@pytest.mark.django_db
def test_create_asset_duplicate_name_personal():
    user = _user()
    create_asset(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        name="Dup",
        weight=Decimal("1"),
        current_amount=Decimal("0"),
        target_amount=Decimal("0"),
        currency="CLP",
        family_id=None,
    )
    with pytest.raises(AssetCreateError) as ei:
        create_asset(
            user_id=user.pk,
            scope=SavingsScope.PERSONAL,
            name="Dup",
            weight=Decimal("1"),
            current_amount=Decimal("0"),
            target_amount=Decimal("0"),
            currency="CLP",
            family_id=None,
        )
    assert ei.value.status_code == 409
