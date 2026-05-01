from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError

from savings.models import (
    Asset,
    Distribution,
    DistributionLine,
    Family,
    FamilyMembership,
    SavingsScope,
)
from savings.schemas import CreateAssetRequest, UpdateAssetRequest
from savings.services import (
    AssetMutationError,
    DistributionMutationError,
    create_asset,
    create_distribution,
    delete_asset,
    list_assets,
    update_asset,
)

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

    with pytest.raises(AssetMutationError) as ei:
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
    with pytest.raises(AssetMutationError) as ei:
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
    rows = list_assets(user_id=user.pk, scope=SavingsScope.PERSONAL)
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

    member_rows = list_assets(user_id=member.pk, scope=SavingsScope.FAMILY)
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

    rows = list_assets(user_id=outsider.pk, scope=SavingsScope.FAMILY)
    assert all(r.pk != aid for r in rows)


@pytest.mark.django_db
def test_list_assets_family_empty_without_membership():
    user = _user()
    assert list_assets(user_id=user.pk, scope=SavingsScope.FAMILY) == []


@pytest.mark.django_db
def test_list_assets_personal_excludes_family_rows():
    user = _user()
    fam = Family.objects.create(created_by=user)
    FamilyMembership.objects.create(family=fam, user=user)
    create_asset(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        name="Solo",
        weight=Decimal("1"),
        current_amount=Decimal("0"),
        target_amount=None,
        currency="CLP",
        family_id=None,
    )
    create_asset(
        user_id=user.pk,
        scope=SavingsScope.FAMILY,
        name="Joint",
        weight=Decimal("1"),
        current_amount=Decimal("0"),
        target_amount=None,
        currency="CLP",
        family_id=fam.pk,
    )
    personal = list_assets(user_id=user.pk, scope=SavingsScope.PERSONAL)
    assert len(personal) == 1
    assert personal[0].name == "Solo"


@pytest.mark.django_db
def test_family_membership_at_most_one_per_user():
    user = _user()
    fam_a = Family.objects.create(created_by=user)
    fam_b = Family.objects.create(created_by=user)
    FamilyMembership.objects.create(family=fam_a, user=user)
    with pytest.raises(IntegrityError):
        FamilyMembership.objects.create(family=fam_b, user=user)


@pytest.mark.django_db
def test_update_asset_personal():
    user = _user()
    aid = create_asset(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        name="Old",
        weight=Decimal("1"),
        current_amount=Decimal("0"),
        target_amount=None,
        currency="CLP",
        family_id=None,
    )
    payload = UpdateAssetRequest.model_validate(
        {
            "asset_id": aid,
            "name": "  New  ",
            "weight": Decimal("3"),
            "current_amount": Decimal("12.34"),
            "target_amount": Decimal("99"),
            "currency": "usd",
        }
    )
    row = update_asset(
        user_id=user.pk,
        asset_id=payload.asset_id,
        name=payload.name,
        weight=payload.weight,
        current_amount=payload.current_amount,
        target_amount=payload.target_amount,
        currency=payload.currency,
    )
    assert row.pk == aid
    assert row.name == "New"
    assert row.weight == Decimal("3")
    assert row.current_amount == Decimal("12.34")
    assert row.target_amount == Decimal("99")
    assert row.currency == "USD"


@pytest.mark.django_db
def test_update_asset_family_member_can_edit():
    owner = _user("owner")
    member = _user("member")
    fam = Family.objects.create(created_by=owner)
    FamilyMembership.objects.create(family=fam, user=owner)
    FamilyMembership.objects.create(family=fam, user=member)

    aid = create_asset(
        user_id=owner.pk,
        scope=SavingsScope.FAMILY,
        name="Pot",
        weight=Decimal("1"),
        current_amount=Decimal("0"),
        target_amount=None,
        currency="CLP",
        family_id=fam.pk,
    )
    row = update_asset(
        user_id=member.pk,
        asset_id=aid,
        name="Pot",
        weight=Decimal("2"),
        current_amount=Decimal("5"),
        target_amount=None,
        currency="CLP",
    )
    assert row.weight == Decimal("2")
    assert row.current_amount == Decimal("5")


@pytest.mark.django_db
def test_update_asset_not_found_for_other_user():
    a = _user("a")
    b = _user("b")
    aid = create_asset(
        user_id=a.pk,
        scope=SavingsScope.PERSONAL,
        name="Mine",
        weight=Decimal("1"),
        current_amount=Decimal("0"),
        target_amount=None,
        currency="CLP",
        family_id=None,
    )
    with pytest.raises(AssetMutationError) as ei:
        update_asset(
            user_id=b.pk,
            asset_id=aid,
            name="Stolen",
            weight=Decimal("1"),
            current_amount=Decimal("0"),
            target_amount=None,
            currency="CLP",
        )
    assert ei.value.status_code == 404


@pytest.mark.django_db
def test_update_asset_duplicate_name_conflict():
    user = _user()
    create_asset(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        name="First",
        weight=Decimal("1"),
        current_amount=Decimal("0"),
        target_amount=None,
        currency="CLP",
        family_id=None,
    )
    aid2 = create_asset(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        name="Second",
        weight=Decimal("1"),
        current_amount=Decimal("0"),
        target_amount=None,
        currency="CLP",
        family_id=None,
    )
    with pytest.raises(AssetMutationError) as ei:
        update_asset(
            user_id=user.pk,
            asset_id=aid2,
            name="First",
            weight=Decimal("1"),
            current_amount=Decimal("0"),
            target_amount=None,
            currency="CLP",
        )
    assert ei.value.status_code == 409


@pytest.mark.django_db
def test_delete_asset_ok():
    user = _user()
    aid = create_asset(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        name="Gone",
        weight=Decimal("1"),
        current_amount=Decimal("0"),
        target_amount=None,
        currency="CLP",
        family_id=None,
    )
    delete_asset(user_id=user.pk, asset_id=aid)
    assert not Asset.objects.filter(pk=aid).exists()


@pytest.mark.django_db
def test_delete_asset_blocked_when_distribution_line_exists():
    user = _user()
    aid = create_asset(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        name="Tracked",
        weight=Decimal("1"),
        current_amount=Decimal("0"),
        target_amount=None,
        currency="CLP",
        family_id=None,
    )
    dist = Distribution.objects.create(
        owner_id=user.pk,
        scope=SavingsScope.PERSONAL,
        family=None,
        budget_amount=Decimal("10"),
        currency="CLP",
    )
    DistributionLine.objects.create(
        distribution=dist,
        asset_id=aid,
        allocated_amount=Decimal("10"),
    )
    with pytest.raises(AssetMutationError) as ei:
        delete_asset(user_id=user.pk, asset_id=aid)
    assert ei.value.status_code == 409


@pytest.mark.django_db
def test_create_distribution_personal_updates_balances():
    user = _user()
    a1 = create_asset(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        name="A",
        weight=Decimal("1"),
        current_amount=Decimal("100"),
        target_amount=None,
        currency="CLP",
        family_id=None,
    )
    a2 = create_asset(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        name="B",
        weight=Decimal("1"),
        current_amount=Decimal("50"),
        target_amount=None,
        currency="CLP",
        family_id=None,
    )
    did = create_distribution(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        budget_amount=Decimal("30"),
        currency="CLP",
        family_id=None,
        asset_ids=[a1, a2],
    )
    assert Distribution.objects.filter(pk=did).exists()
    lines = list(
        DistributionLine.objects.filter(distribution_id=did).order_by("asset_id")
    )
    assert len(lines) == 2
    assert sum(line.allocated_amount for line in lines) == Decimal("30")
    assert Asset.objects.get(pk=a1).current_amount == Decimal("115")
    assert Asset.objects.get(pk=a2).current_amount == Decimal("65")


@pytest.mark.django_db
def test_create_distribution_rejects_zero_total_weight():
    user = _user()
    a1 = create_asset(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        name="A",
        weight=Decimal("0"),
        current_amount=Decimal("0"),
        target_amount=None,
        currency="CLP",
        family_id=None,
    )
    a2 = create_asset(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        name="B",
        weight=Decimal("0"),
        current_amount=Decimal("0"),
        target_amount=None,
        currency="CLP",
        family_id=None,
    )
    with pytest.raises(DistributionMutationError) as ei:
        create_distribution(
            user_id=user.pk,
            scope=SavingsScope.PERSONAL,
            budget_amount=Decimal("100"),
            currency="CLP",
            family_id=None,
            asset_ids=[a1, a2],
        )
    assert ei.value.status_code == 400


@pytest.mark.django_db
def test_create_distribution_requires_assets():
    user = _user()
    with pytest.raises(DistributionMutationError) as ei:
        create_distribution(
            user_id=user.pk,
            scope=SavingsScope.PERSONAL,
            budget_amount=Decimal("0"),
            currency="CLP",
            family_id=None,
            asset_ids=[],
        )
    assert ei.value.status_code == 400


@pytest.mark.django_db
def test_create_distribution_family_member_ok():
    owner = _user("owner")
    member = _user("member")
    fam = Family.objects.create(created_by=owner)
    FamilyMembership.objects.create(family=fam, user=owner)
    FamilyMembership.objects.create(family=fam, user=member)

    aid = create_asset(
        user_id=owner.pk,
        scope=SavingsScope.FAMILY,
        name="Pot",
        weight=Decimal("1"),
        current_amount=Decimal("0"),
        target_amount=None,
        currency="CLP",
        family_id=fam.pk,
    )
    create_distribution(
        user_id=member.pk,
        scope=SavingsScope.FAMILY,
        budget_amount=Decimal("25"),
        currency="CLP",
        family_id=fam.pk,
        asset_ids=[aid],
    )
    assert Asset.objects.get(pk=aid).current_amount == Decimal("25")


@pytest.mark.django_db
def test_create_distribution_weighted_split():
    user = _user()
    heavy_id = create_asset(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        name="Heavy",
        weight=Decimal("3"),
        current_amount=Decimal("0"),
        target_amount=None,
        currency="CLP",
        family_id=None,
    )
    light_id = create_asset(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        name="Light",
        weight=Decimal("1"),
        current_amount=Decimal("0"),
        target_amount=None,
        currency="CLP",
        family_id=None,
    )
    create_distribution(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        budget_amount=Decimal("100"),
        currency="CLP",
        family_id=None,
        asset_ids=[heavy_id, light_id],
    )
    h = Asset.objects.get(pk=heavy_id).current_amount
    ell = Asset.objects.get(pk=light_id).current_amount
    assert h == Decimal("75")
    assert ell == Decimal("25")
    assert h + ell == Decimal("100")


@pytest.mark.django_db
def test_create_distribution_clp_rejects_fractional_budget():
    user = _user()
    a1 = create_asset(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        name="A",
        weight=Decimal("1"),
        current_amount=Decimal("0"),
        target_amount=None,
        currency="CLP",
        family_id=None,
    )
    a2 = create_asset(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        name="B",
        weight=Decimal("1"),
        current_amount=Decimal("0"),
        target_amount=None,
        currency="CLP",
        family_id=None,
    )
    with pytest.raises(DistributionMutationError) as ei:
        create_distribution(
            user_id=user.pk,
            scope=SavingsScope.PERSONAL,
            budget_amount=Decimal("10.50"),
            currency="CLP",
            family_id=None,
            asset_ids=[a1, a2],
        )
    assert ei.value.status_code == 400


@pytest.mark.django_db
def test_create_distribution_clp_integer_split_remainder():
    user = _user()
    heavy_id = create_asset(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        name="Heavy",
        weight=Decimal("3"),
        current_amount=Decimal("0"),
        target_amount=None,
        currency="CLP",
        family_id=None,
    )
    light_id = create_asset(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        name="Light",
        weight=Decimal("1"),
        current_amount=Decimal("0"),
        target_amount=None,
        currency="CLP",
        family_id=None,
    )
    did = create_distribution(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        budget_amount=Decimal("10"),
        currency="CLP",
        family_id=None,
        asset_ids=[heavy_id, light_id],
    )
    lines = {line.asset_id: line.allocated_amount for line in DistributionLine.objects.filter(distribution_id=did)}
    assert lines[heavy_id] == Decimal("8")
    assert lines[light_id] == Decimal("2")
    assert sum(lines.values()) == Decimal("10")


@pytest.mark.django_db
def test_create_distribution_non_clp_uses_cents():
    user = _user()
    a1 = create_asset(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        name="A",
        weight=Decimal("1"),
        current_amount=Decimal("0"),
        target_amount=None,
        currency="USD",
        family_id=None,
    )
    a2 = create_asset(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        name="B",
        weight=Decimal("1"),
        current_amount=Decimal("0"),
        target_amount=None,
        currency="USD",
        family_id=None,
    )
    did = create_distribution(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        budget_amount=Decimal("1.00"),
        currency="USD",
        family_id=None,
        asset_ids=[a1, a2],
    )
    lines = [line.allocated_amount for line in DistributionLine.objects.filter(distribution_id=did).order_by("id")]
    assert lines == [Decimal("0.50"), Decimal("0.50")]


@pytest.mark.django_db
def test_create_distribution_rejects_asset_wrong_scope():
    user = _user()
    personal_id = create_asset(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        name="Solo",
        weight=Decimal("1"),
        current_amount=Decimal("0"),
        target_amount=None,
        currency="CLP",
        family_id=None,
    )
    fam = Family.objects.create(created_by=user)
    FamilyMembership.objects.create(family=fam, user=user)
    with pytest.raises(DistributionMutationError) as ei:
        create_distribution(
            user_id=user.pk,
            scope=SavingsScope.FAMILY,
            budget_amount=Decimal("1"),
            currency="CLP",
            family_id=fam.pk,
            asset_ids=[personal_id],
        )
    assert ei.value.status_code == 400
