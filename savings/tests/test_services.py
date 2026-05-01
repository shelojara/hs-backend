from decimal import Decimal
from unittest.mock import call, patch

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError

from savings.models import (
    Asset,
    AssetState,
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
    list_distributions,
    rush_asset,
    set_asset_completion,
    simulate_distribution,
    simulate_rush_asset,
    update_asset,
    update_distribution_notes,
)

User = get_user_model()


def _user(username: str = "u1"):
    return User.objects.create_user(username=username, password="pw")


@pytest.mark.django_db
@patch("savings.services.gemini_service.suggest_asset_emoji", return_value="💸")
def test_create_asset_persists_gemini_emoji(mock_emoji):
    user = _user()
    aid = create_asset(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        name="Rainy day",
        weight=Decimal("1"),
        current_amount=Decimal("0"),
        target_amount=None,
        currency="CLP",
    )
    row = Asset.objects.get(pk=aid)
    assert row.emoji == "💸"
    mock_emoji.assert_called_once_with(name="Rainy day")


@pytest.mark.django_db
@patch(
    "savings.services.gemini_service.suggest_asset_emoji",
    side_effect=RuntimeError("no key"),
)
def test_create_asset_unconfigured_gemini_emoji_empty(_mock_emoji):
    user = _user()
    aid = create_asset(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        name="No key",
        weight=Decimal("1"),
        current_amount=Decimal("0"),
        target_amount=None,
        currency="CLP",
    )
    assert Asset.objects.get(pk=aid).emoji == ""


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
        )
    assert ei.value.status_code == 400


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
    )
    create_asset(
        user_id=user.pk,
        scope=SavingsScope.FAMILY,
        name="Joint",
        weight=Decimal("1"),
        current_amount=Decimal("0"),
        target_amount=None,
        currency="CLP",
    )
    personal = list_assets(user_id=user.pk, scope=SavingsScope.PERSONAL)
    assert len(personal) == 1
    assert personal[0].name == "Solo"


@pytest.mark.django_db
def test_list_distributions_personal_with_lines():
    user = _user()
    aid = create_asset(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        name="Pot",
        weight=Decimal("1"),
        current_amount=Decimal("0"),
        target_amount=None,
        currency="CLP",
    )
    did = create_distribution(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        budget_amount=Decimal("100"),
        currency="CLP",
        asset_ids=[aid],
    )
    rows = list_distributions(user_id=user.pk, scope=SavingsScope.PERSONAL)
    assert len(rows) == 1
    d = rows[0]
    assert d.pk == did
    assert d.budget_amount == Decimal("100")
    line_list = list(d.lines.all())
    assert len(line_list) == 1
    assert line_list[0].asset_id == aid
    assert line_list[0].allocated_amount == Decimal("100")


@pytest.mark.django_db
def test_list_distributions_family_visible_to_member():
    owner = _user("owner")
    member = _user("member")
    fam = Family.objects.create(created_by=owner)
    FamilyMembership.objects.create(family=fam, user=owner)
    FamilyMembership.objects.create(family=fam, user=member)

    aid = create_asset(
        user_id=owner.pk,
        scope=SavingsScope.FAMILY,
        name="Shared",
        weight=Decimal("1"),
        current_amount=Decimal("0"),
        target_amount=None,
        currency="CLP",
    )
    did = create_distribution(
        user_id=owner.pk,
        scope=SavingsScope.FAMILY,
        budget_amount=Decimal("50"),
        currency="CLP",
        asset_ids=[aid],
    )
    member_rows = list_distributions(user_id=member.pk, scope=SavingsScope.FAMILY)
    assert len(member_rows) == 1
    assert member_rows[0].pk == did
    assert list(member_rows[0].lines.all())[0].allocated_amount == Decimal("50")


@pytest.mark.django_db
def test_list_distributions_family_hidden_from_non_member():
    owner = _user("owner")
    outsider = _user("outsider")
    fam = Family.objects.create(created_by=owner)
    FamilyMembership.objects.create(family=fam, user=owner)

    aid = create_asset(
        user_id=owner.pk,
        scope=SavingsScope.FAMILY,
        name="Fam goal",
        weight=Decimal("1"),
        current_amount=Decimal("0"),
        target_amount=None,
        currency="CLP",
    )
    create_distribution(
        user_id=owner.pk,
        scope=SavingsScope.FAMILY,
        budget_amount=Decimal("10"),
        currency="CLP",
        asset_ids=[aid],
    )
    assert list_distributions(user_id=outsider.pk, scope=SavingsScope.FAMILY) == []


@pytest.mark.django_db
def test_list_distributions_personal_excludes_family():
    user = _user()
    fam = Family.objects.create(created_by=user)
    FamilyMembership.objects.create(family=fam, user=user)
    fam_aid = create_asset(
        user_id=user.pk,
        scope=SavingsScope.FAMILY,
        name="Joint",
        weight=Decimal("1"),
        current_amount=Decimal("0"),
        target_amount=None,
        currency="CLP",
    )
    create_distribution(
        user_id=user.pk,
        scope=SavingsScope.FAMILY,
        budget_amount=Decimal("20"),
        currency="CLP",
        asset_ids=[fam_aid],
    )
    assert list_distributions(user_id=user.pk, scope=SavingsScope.PERSONAL) == []


@pytest.mark.django_db
def test_list_distributions_pagination_offset_limit():
    user = _user()
    aid = create_asset(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        name="Pot",
        weight=Decimal("1"),
        current_amount=Decimal("0"),
        target_amount=None,
        currency="CLP",
    )
    budgets = [Decimal("10"), Decimal("20"), Decimal("30")]
    ids: list[int] = []
    for b in budgets:
        ids.append(
            create_distribution(
                user_id=user.pk,
                scope=SavingsScope.PERSONAL,
                budget_amount=b,
                currency="CLP",
                asset_ids=[aid],
            )
        )
    newest_first = list(reversed(ids))
    page0 = list_distributions(
        user_id=user.pk, scope=SavingsScope.PERSONAL, limit=1, offset=0
    )
    assert [d.pk for d in page0] == [newest_first[0]]
    page1 = list_distributions(
        user_id=user.pk, scope=SavingsScope.PERSONAL, limit=1, offset=1
    )
    assert [d.pk for d in page1] == [newest_first[1]]
    page01 = list_distributions(
        user_id=user.pk, scope=SavingsScope.PERSONAL, limit=2, offset=0
    )
    assert [d.pk for d in page01] == newest_first[:2]
    beyond = list_distributions(
        user_id=user.pk, scope=SavingsScope.PERSONAL, limit=10, offset=99
    )
    assert beyond == []


@pytest.mark.django_db
def test_list_distributions_clamps_limit_in_service():
    user = _user()
    aid = create_asset(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        name="Pot",
        weight=Decimal("1"),
        current_amount=Decimal("0"),
        target_amount=None,
        currency="CLP",
    )
    for i in range(3):
        create_distribution(
            user_id=user.pk,
            scope=SavingsScope.PERSONAL,
            budget_amount=Decimal(i + 1),
            currency="CLP",
            asset_ids=[aid],
        )
    rows = list_distributions(
        user_id=user.pk, scope=SavingsScope.PERSONAL, limit=500, offset=0
    )
    assert len(rows) == 3


@pytest.mark.django_db
def test_family_membership_at_most_one_per_user():
    user = _user()
    fam_a = Family.objects.create(created_by=user)
    fam_b = Family.objects.create(created_by=user)
    FamilyMembership.objects.create(family=fam_a, user=user)
    with pytest.raises(IntegrityError):
        FamilyMembership.objects.create(family=fam_b, user=user)


@pytest.mark.django_db
@patch("savings.services.gemini_service.suggest_asset_emoji", side_effect=["", "🏠"])
def test_update_asset_renames_refreshes_emoji(mock_emoji):
    user = _user()
    aid = create_asset(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        name="Fund",
        weight=Decimal("1"),
        current_amount=Decimal("0"),
        target_amount=None,
        currency="CLP",
    )
    row = update_asset(
        user_id=user.pk,
        asset_id=aid,
        name="House deposit",
        weight=Decimal("1"),
        current_amount=Decimal("0"),
        target_amount=None,
        currency="CLP",
    )
    assert row.emoji == "🏠"
    assert mock_emoji.call_args_list == [
        call(name="Fund"),
        call(name="House deposit"),
    ]


@pytest.mark.django_db
@patch(
    "savings.services.gemini_service.suggest_asset_emoji",
    return_value="📌",
)
def test_update_asset_same_name_preserves_emoji(mock_emoji):
    user = _user()
    aid = create_asset(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        name="Stable",
        weight=Decimal("1"),
        current_amount=Decimal("0"),
        target_amount=None,
        currency="CLP",
    )
    Asset.objects.filter(pk=aid).update(emoji="🔒")
    update_asset(
        user_id=user.pk,
        asset_id=aid,
        name="Stable",
        weight=Decimal("2"),
        current_amount=Decimal("10"),
        target_amount=None,
        currency="CLP",
    )
    assert Asset.objects.get(pk=aid).emoji == "🔒"
    mock_emoji.assert_called_once_with(name="Stable")


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
    )
    aid2 = create_asset(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        name="Second",
        weight=Decimal("1"),
        current_amount=Decimal("0"),
        target_amount=None,
        currency="CLP",
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
def test_update_asset_rejects_target_below_current():
    user = _user()
    aid = create_asset(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        name="Goal",
        weight=Decimal("1"),
        current_amount=Decimal("50"),
        target_amount=Decimal("100"),
        currency="CLP",
    )
    with pytest.raises(AssetMutationError) as ei:
        update_asset(
            user_id=user.pk,
            asset_id=aid,
            name="Goal",
            weight=Decimal("1"),
            current_amount=Decimal("50"),
            target_amount=Decimal("40"),
            currency="CLP",
        )
    assert ei.value.status_code == 400
    assert "Target amount cannot be below current amount." in str(ei.value)


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
    )
    delete_asset(user_id=user.pk, asset_id=aid)
    assert not Asset.objects.filter(pk=aid).exists()


@pytest.mark.django_db
def test_delete_asset_removes_distribution_lines_then_row():
    user = _user()
    aid = create_asset(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        name="Tracked",
        weight=Decimal("1"),
        current_amount=Decimal("0"),
        target_amount=None,
        currency="CLP",
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
    delete_asset(user_id=user.pk, asset_id=aid)
    assert not Asset.objects.filter(pk=aid).exists()
    assert not DistributionLine.objects.filter(asset_id=aid).exists()
    dist.refresh_from_db()
    assert dist.budget_amount == Decimal("0")
    assert Distribution.objects.filter(pk=dist.pk).exists()


@pytest.mark.django_db
def test_delete_asset_updates_distribution_budget_to_sum_of_remaining_lines():
    user = _user()
    remove_me = create_asset(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        name="Drop",
        weight=Decimal("1"),
        current_amount=Decimal("0"),
        target_amount=None,
        currency="CLP",
    )
    keep_me = create_asset(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        name="Keep",
        weight=Decimal("1"),
        current_amount=Decimal("0"),
        target_amount=None,
        currency="CLP",
    )
    dist = Distribution.objects.create(
        owner_id=user.pk,
        scope=SavingsScope.PERSONAL,
        family=None,
        budget_amount=Decimal("30"),
        currency="CLP",
    )
    DistributionLine.objects.create(
        distribution=dist,
        asset_id=remove_me,
        allocated_amount=Decimal("10"),
    )
    DistributionLine.objects.create(
        distribution=dist,
        asset_id=keep_me,
        allocated_amount=Decimal("20"),
    )
    delete_asset(user_id=user.pk, asset_id=remove_me)
    dist.refresh_from_db()
    assert dist.budget_amount == Decimal("20")
    assert (
        DistributionLine.objects.filter(distribution_id=dist.pk).count() == 1
    )
    assert DistributionLine.objects.get(distribution_id=dist.pk).asset_id == keep_me


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
    )
    a2 = create_asset(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        name="B",
        weight=Decimal("1"),
        current_amount=Decimal("50"),
        target_amount=None,
        currency="CLP",
    )
    did = create_distribution(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        budget_amount=Decimal("30"),
        currency="CLP",
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
def test_create_distribution_stores_notes():
    user = _user()
    aid = create_asset(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        name="A",
        weight=Decimal("1"),
        current_amount=Decimal("0"),
        target_amount=None,
        currency="CLP",
    )
    did = create_distribution(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        budget_amount=Decimal("10"),
        currency="CLP",
        asset_ids=[aid],
        notes="payroll May",
    )
    assert Distribution.objects.get(pk=did).notes == "payroll May"


@pytest.mark.django_db
def test_update_distribution_notes_personal_ok():
    user = _user()
    aid = create_asset(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        name="A",
        weight=Decimal("1"),
        current_amount=Decimal("0"),
        target_amount=None,
        currency="CLP",
    )
    did = create_distribution(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        budget_amount=Decimal("10"),
        currency="CLP",
        asset_ids=[aid],
        notes="old",
    )
    update_distribution_notes(
        user_id=user.pk,
        distribution_id=did,
        notes="new note",
    )
    assert Distribution.objects.get(pk=did).notes == "new note"


@pytest.mark.django_db
def test_update_distribution_notes_family_member_ok():
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
    )
    did = create_distribution(
        user_id=member.pk,
        scope=SavingsScope.FAMILY,
        budget_amount=Decimal("25"),
        currency="CLP",
        asset_ids=[aid],
        notes="before",
    )
    update_distribution_notes(
        user_id=owner.pk,
        distribution_id=did,
        notes="after",
    )
    assert Distribution.objects.get(pk=did).notes == "after"


@pytest.mark.django_db
def test_update_distribution_notes_not_found_wrong_user():
    user_a = _user("a")
    user_b = _user("b")
    aid = create_asset(
        user_id=user_a.pk,
        scope=SavingsScope.PERSONAL,
        name="A",
        weight=Decimal("1"),
        current_amount=Decimal("0"),
        target_amount=None,
        currency="CLP",
    )
    did = create_distribution(
        user_id=user_a.pk,
        scope=SavingsScope.PERSONAL,
        budget_amount=Decimal("10"),
        currency="CLP",
        asset_ids=[aid],
    )
    with pytest.raises(DistributionMutationError) as ei:
        update_distribution_notes(
            user_id=user_b.pk,
            distribution_id=did,
            notes="nope",
        )
    assert ei.value.status_code == 404


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
    )
    a2 = create_asset(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        name="B",
        weight=Decimal("0"),
        current_amount=Decimal("0"),
        target_amount=None,
        currency="CLP",
    )
    with pytest.raises(DistributionMutationError) as ei:
        create_distribution(
            user_id=user.pk,
            scope=SavingsScope.PERSONAL,
            budget_amount=Decimal("100"),
            currency="CLP",
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
    )
    create_distribution(
        user_id=member.pk,
        scope=SavingsScope.FAMILY,
        budget_amount=Decimal("25"),
        currency="CLP",
        asset_ids=[aid],
    )
    assert Asset.objects.get(pk=aid).current_amount == Decimal("25")


@pytest.mark.django_db
def test_simulate_distribution_matches_split_without_side_effects():
    user = _user()
    heavy_id = create_asset(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        name="Heavy",
        weight=Decimal("3"),
        current_amount=Decimal("10"),
        target_amount=None,
        currency="CLP",
    )
    light_id = create_asset(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        name="Light",
        weight=Decimal("1"),
        current_amount=Decimal("20"),
        target_amount=None,
        currency="CLP",
    )
    lines = simulate_distribution(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        budget_amount=Decimal("100"),
        currency="CLP",
        asset_ids=[heavy_id, light_id],
    )
    by_asset = dict(lines)
    assert by_asset[heavy_id] == Decimal("75")
    assert by_asset[light_id] == Decimal("25")
    assert Distribution.objects.count() == 0
    assert Asset.objects.get(pk=heavy_id).current_amount == Decimal("10")
    assert Asset.objects.get(pk=light_id).current_amount == Decimal("20")


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
    )
    light_id = create_asset(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        name="Light",
        weight=Decimal("1"),
        current_amount=Decimal("0"),
        target_amount=None,
        currency="CLP",
    )
    create_distribution(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        budget_amount=Decimal("100"),
        currency="CLP",
        asset_ids=[heavy_id, light_id],
    )
    h = Asset.objects.get(pk=heavy_id).current_amount
    ell = Asset.objects.get(pk=light_id).current_amount
    assert h == Decimal("75")
    assert ell == Decimal("25")
    assert h + ell == Decimal("100")


@pytest.mark.django_db
def test_simulate_distribution_caps_at_target_then_redistributes():
    user = _user()
    capped_id = create_asset(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        name="NearGoal",
        weight=Decimal("1"),
        current_amount=Decimal("90"),
        target_amount=Decimal("100"),
        currency="CLP",
    )
    sink_id = create_asset(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        name="Sink",
        weight=Decimal("1"),
        current_amount=Decimal("0"),
        target_amount=None,
        currency="CLP",
    )
    lines = dict(
        simulate_distribution(
            user_id=user.pk,
            scope=SavingsScope.PERSONAL,
            budget_amount=Decimal("100"),
            currency="CLP",
            asset_ids=[capped_id, sink_id],
        )
    )
    assert lines[capped_id] == Decimal("10")
    assert lines[sink_id] == Decimal("90")


@pytest.mark.django_db
def test_create_distribution_partial_budget_when_targets_saturate():
    user = _user()
    a1 = create_asset(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        name="Gap10",
        weight=Decimal("1"),
        current_amount=Decimal("90"),
        target_amount=Decimal("100"),
        currency="CLP",
    )
    a2 = create_asset(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        name="Gap20",
        weight=Decimal("1"),
        current_amount=Decimal("0"),
        target_amount=Decimal("20"),
        currency="CLP",
    )
    did = create_distribution(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        budget_amount=Decimal("100"),
        currency="CLP",
        asset_ids=[a1, a2],
    )
    dist = Distribution.objects.get(pk=did)
    assert dist.budget_amount == Decimal("30")
    by_asset = {
        line.asset_id: line.allocated_amount
        for line in DistributionLine.objects.filter(distribution_id=did)
    }
    assert by_asset[a1] == Decimal("10")
    assert by_asset[a2] == Decimal("20")
    assert Asset.objects.get(pk=a1).current_amount == Decimal("100")
    assert Asset.objects.get(pk=a2).current_amount == Decimal("20")


@pytest.mark.django_db
def test_create_distribution_rejects_when_all_selected_at_or_above_target():
    user = _user()
    a1 = create_asset(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        name="Full1",
        weight=Decimal("1"),
        current_amount=Decimal("100"),
        target_amount=Decimal("100"),
        currency="CLP",
    )
    a2 = create_asset(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        name="Full2",
        weight=Decimal("1"),
        current_amount=Decimal("50"),
        target_amount=Decimal("50"),
        currency="CLP",
    )
    with pytest.raises(DistributionMutationError) as ei:
        create_distribution(
            user_id=user.pk,
            scope=SavingsScope.PERSONAL,
            budget_amount=Decimal("10"),
            currency="CLP",
            asset_ids=[a1, a2],
        )
    assert ei.value.status_code == 400


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
    )
    a2 = create_asset(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        name="B",
        weight=Decimal("1"),
        current_amount=Decimal("0"),
        target_amount=None,
        currency="CLP",
    )
    with pytest.raises(DistributionMutationError) as ei:
        create_distribution(
            user_id=user.pk,
            scope=SavingsScope.PERSONAL,
            budget_amount=Decimal("10.50"),
            currency="CLP",
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
    )
    light_id = create_asset(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        name="Light",
        weight=Decimal("1"),
        current_amount=Decimal("0"),
        target_amount=None,
        currency="CLP",
    )
    did = create_distribution(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        budget_amount=Decimal("10"),
        currency="CLP",
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
    )
    a2 = create_asset(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        name="B",
        weight=Decimal("1"),
        current_amount=Decimal("0"),
        target_amount=None,
        currency="USD",
    )
    did = create_distribution(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        budget_amount=Decimal("1.00"),
        currency="USD",
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
    )
    fam = Family.objects.create(created_by=user)
    FamilyMembership.objects.create(family=fam, user=user)
    with pytest.raises(DistributionMutationError) as ei:
        create_distribution(
            user_id=user.pk,
            scope=SavingsScope.FAMILY,
            budget_amount=Decimal("1"),
            currency="CLP",
            asset_ids=[personal_id],
        )
    assert ei.value.status_code == 400


@pytest.mark.django_db
def test_create_distribution_rejects_completed_asset():
    user = _user()
    aid = create_asset(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        name="Done",
        weight=Decimal("1"),
        current_amount=Decimal("0"),
        target_amount=None,
        currency="CLP",
    )
    set_asset_completion(user_id=user.pk, asset_id=aid, completed=True)
    with pytest.raises(DistributionMutationError) as ei:
        create_distribution(
            user_id=user.pk,
            scope=SavingsScope.PERSONAL,
            budget_amount=Decimal("10"),
            currency="CLP",
            asset_ids=[aid],
        )
    assert ei.value.status_code == 400


@pytest.mark.django_db
def test_rush_rejects_completed_beneficiary():
    user = _user()
    ben = create_asset(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        name="Goal",
        weight=Decimal("1"),
        current_amount=Decimal("0"),
        target_amount=Decimal("100"),
        currency="CLP",
    )
    create_asset(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        name="Pot",
        weight=Decimal("1"),
        current_amount=Decimal("500"),
        target_amount=None,
        currency="CLP",
    )
    set_asset_completion(user_id=user.pk, asset_id=ben, completed=True)
    with pytest.raises(DistributionMutationError) as ei:
        rush_asset(user_id=user.pk, beneficiary_asset_id=ben)
    assert ei.value.status_code == 400


@pytest.mark.django_db
def test_rush_skips_completed_donor():
    user = _user()
    rush_id = create_asset(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        name="Need",
        weight=Decimal("1"),
        current_amount=Decimal("0"),
        target_amount=Decimal("50"),
        currency="CLP",
    )
    done_donor = create_asset(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        name="FinishedPot",
        weight=Decimal("1"),
        current_amount=Decimal("999"),
        target_amount=None,
        currency="CLP",
    )
    active_donor = create_asset(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        name="ActivePot",
        weight=Decimal("1"),
        current_amount=Decimal("500"),
        target_amount=None,
        currency="CLP",
    )
    set_asset_completion(user_id=user.pk, asset_id=done_donor, completed=True)
    rush_asset(user_id=user.pk, beneficiary_asset_id=rush_id)
    assert Asset.objects.get(pk=done_donor).current_amount == Decimal("999")
    assert Asset.objects.get(pk=active_donor).current_amount == Decimal("450")
    assert Asset.objects.get(pk=rush_id).current_amount == Decimal("50")


@pytest.mark.django_db
def test_set_asset_completion_toggles_state():
    user = _user()
    aid = create_asset(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        name="G",
        weight=Decimal("1"),
        current_amount=Decimal("0"),
        target_amount=None,
        currency="CLP",
    )
    assert Asset.objects.get(pk=aid).state == AssetState.ACTIVE
    set_asset_completion(user_id=user.pk, asset_id=aid, completed=True)
    assert Asset.objects.get(pk=aid).state == AssetState.COMPLETED
    set_asset_completion(user_id=user.pk, asset_id=aid, completed=False)
    assert Asset.objects.get(pk=aid).state == AssetState.ACTIVE


@pytest.mark.django_db
def test_rush_asset_weighted_split_fills_gap():
    user = _user()
    rush_id = create_asset(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        name="RushMe",
        weight=Decimal("1"),
        current_amount=Decimal("50"),
        target_amount=Decimal("150"),
        currency="CLP",
    )
    d1 = create_asset(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        name="D1",
        weight=Decimal("3"),
        current_amount=Decimal("200"),
        target_amount=None,
        currency="CLP",
    )
    d2 = create_asset(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        name="D2",
        weight=Decimal("1"),
        current_amount=Decimal("200"),
        target_amount=None,
        currency="CLP",
    )
    did, ben = rush_asset(user_id=user.pk, beneficiary_asset_id=rush_id)
    dist = Distribution.objects.get(pk=did)
    assert "Rush toward target" in dist.notes
    assert str(rush_id) in dist.notes
    assert "RushMe" in dist.notes
    assert dist.budget_amount == Decimal("0")
    assert ben.current_amount == Decimal("150")
    assert Asset.objects.get(pk=d1).current_amount == Decimal("125")
    assert Asset.objects.get(pk=d2).current_amount == Decimal("175")
    lines = list(DistributionLine.objects.filter(distribution_id=did).order_by("asset_id"))
    assert sum(line.allocated_amount for line in lines) == Decimal("0")
    by_asset = {line.asset_id: line.allocated_amount for line in lines}
    assert by_asset[rush_id] == Decimal("100")
    assert by_asset[d1] == Decimal("-75")
    assert by_asset[d2] == Decimal("-25")


@pytest.mark.django_db
def test_rush_asset_iterative_when_donor_balances_exhausted():
    user = _user()
    rush_id = create_asset(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        name="Goal",
        weight=Decimal("1"),
        current_amount=Decimal("0"),
        target_amount=Decimal("100"),
        currency="CLP",
    )
    capped = create_asset(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        name="Cap10",
        weight=Decimal("1"),
        current_amount=Decimal("110"),
        target_amount=Decimal("100"),
        currency="CLP",
    )
    deep = create_asset(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        name="Deep",
        weight=Decimal("1"),
        current_amount=Decimal("500"),
        target_amount=None,
        currency="CLP",
    )
    did, ben = rush_asset(user_id=user.pk, beneficiary_asset_id=rush_id)
    assert ben.current_amount == Decimal("100")
    # Donor targets ignored: split 50/50 by equal weight until gap filled.
    assert Asset.objects.get(pk=capped).current_amount == Decimal("60")
    assert Asset.objects.get(pk=deep).current_amount == Decimal("450")
    dist = Distribution.objects.get(pk=did)
    assert dist.budget_amount == Decimal("0")


@pytest.mark.django_db
def test_rush_asset_rejects_without_target():
    user = _user()
    aid = create_asset(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        name="Open",
        weight=Decimal("1"),
        current_amount=Decimal("10"),
        target_amount=None,
        currency="CLP",
    )
    create_asset(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        name="Pot",
        weight=Decimal("1"),
        current_amount=Decimal("50"),
        target_amount=None,
        currency="CLP",
    )
    with pytest.raises(DistributionMutationError) as ei:
        rush_asset(user_id=user.pk, beneficiary_asset_id=aid)
    assert ei.value.status_code == 400


@pytest.mark.django_db
def test_rush_asset_rejects_when_no_eligible_donors():
    user = _user()
    rush_id = create_asset(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        name="Need",
        weight=Decimal("1"),
        current_amount=Decimal("0"),
        target_amount=Decimal("50"),
        currency="CLP",
    )
    create_asset(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        name="Empty",
        weight=Decimal("1"),
        current_amount=Decimal("0"),
        target_amount=Decimal("100"),
        currency="CLP",
    )
    with pytest.raises(DistributionMutationError) as ei:
        rush_asset(user_id=user.pk, beneficiary_asset_id=rush_id)
    assert ei.value.status_code == 400


@pytest.mark.django_db
def test_rush_asset_skips_wrong_currency_donors():
    user = _user()
    rush_id = create_asset(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        name="CLPGoal",
        weight=Decimal("1"),
        current_amount=Decimal("0"),
        target_amount=Decimal("30"),
        currency="CLP",
    )
    create_asset(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        name="USDOnly",
        weight=Decimal("1"),
        current_amount=Decimal("999"),
        target_amount=None,
        currency="USD",
    )
    same = create_asset(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        name="CLPPot",
        weight=Decimal("1"),
        current_amount=Decimal("100"),
        target_amount=None,
        currency="CLP",
    )
    rush_asset(user_id=user.pk, beneficiary_asset_id=rush_id)
    assert Asset.objects.get(pk=same).current_amount == Decimal("70")


@pytest.mark.django_db
def test_simulate_rush_asset_matches_rush_lines_and_skips_writes():
    user = _user()
    rush_id = create_asset(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        name="RushMe",
        weight=Decimal("1"),
        current_amount=Decimal("50"),
        target_amount=Decimal("150"),
        currency="CLP",
    )
    create_asset(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        name="D1",
        weight=Decimal("3"),
        current_amount=Decimal("200"),
        target_amount=None,
        currency="CLP",
    )
    create_asset(
        user_id=user.pk,
        scope=SavingsScope.PERSONAL,
        name="D2",
        weight=Decimal("1"),
        current_amount=Decimal("200"),
        target_amount=None,
        currency="CLP",
    )
    preview = simulate_rush_asset(user_id=user.pk, beneficiary_asset_id=rush_id)
    assert Distribution.objects.count() == 0
    assert Asset.objects.get(pk=rush_id).current_amount == Decimal("50")

    did, _ben = rush_asset(user_id=user.pk, beneficiary_asset_id=rush_id)
    by_asset = {
        line.asset_id: line.allocated_amount
        for line in DistributionLine.objects.filter(distribution_id=did)
    }
    assert dict(preview) == by_asset
