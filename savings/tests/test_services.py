from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from savings.models import Asset, Family, FamilyMembership, SavingsScope
from savings.schemas import CreateAssetRequest
from savings.services import AssetCreateError, create_asset, list_assets

User = get_user_model()


def _user(username: str = "u1"):
    return User.objects.create_user(username=username, password="pw")


@pytest.mark.django_db
def test_create_asset_personal():
    user = _user()
    payload = CreateAssetRequest.model_validate(
        {
            "scope": SavingsScope.PERSONAL,
            "name": "  Emergency  ",
            "weight": Decimal("2"),
            "current_amount": Decimal("10.50"),
            "target_amount": Decimal("100"),
            "currency": "clp",
            "family_id": None,
        }
    )
    aid = create_asset(
        user_id=user.pk,
        scope=payload.scope,
        name=payload.name,
        weight=payload.weight,
        current_amount=payload.current_amount,
        target_amount=payload.target_amount,
        currency=payload.currency,
        family_id=payload.family_id,
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


@pytest.mark.django_db
def test_list_assets_personal_only():
    user = _user()
    aid = create_asset(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        name="Rainy day",
        weight=Decimal("1"),
        current_amount=Decimal("5"),
        target_amount=None,
        currency="CLP",
        family_id=None,
    )
    rows = list_assets(user_id=user.pk)
    assert len(rows) == 1
    assert rows[0].pk == aid
    assert rows[0].name == "Rainy day"


@pytest.mark.django_db
def test_list_assets_family_visible_to_other_member():
    owner = _user("owner")
    member = _user("member")
    fam = Family.objects.create(created_by=owner)
    FamilyMembership.objects.create(family=fam, user=owner)
    FamilyMembership.objects.create(family=fam, user=member)

    aid = create_asset(
        user_id=owner.pk,
        scope=SavingsScope.FAMILY,
        name="Shared pot",
        weight=Decimal("1"),
        current_amount=Decimal("0"),
        target_amount=Decimal("100"),
        currency="CLP",
        family_id=fam.pk,
    )

    member_rows = list_assets(user_id=member.pk)
    ids = {r.pk for r in member_rows}
    assert aid in ids
    shared = next(r for r in member_rows if r.pk == aid)
    assert shared.owner_id == owner.pk


@pytest.mark.django_db
def test_list_assets_family_hidden_from_non_member():
    owner = _user("owner")
    outsider = _user("outsider")
    fam = Family.objects.create(created_by=owner)
    FamilyMembership.objects.create(family=fam, user=owner)

    aid = create_asset(
        user_id=owner.pk,
        scope=SavingsScope.FAMILY,
        name="Private family goal",
        weight=Decimal("1"),
        current_amount=Decimal("0"),
        target_amount=None,
        currency="CLP",
        family_id=fam.pk,
    )

    rows = list_assets(user_id=outsider.pk)
    assert all(r.pk != aid for r in rows)
