"""Business logic for savings app."""

import logging
from decimal import ROUND_DOWN, Decimal

from django.db import IntegrityError, transaction
from django.db.models import Sum

from savings import gemini_service
from savings.models import (
    Asset,
    Distribution,
    DistributionLine,
    Family,
    FamilyMembership,
    SavingsScope,
)

_LIST_DISTRIBUTIONS_DEFAULT_LIMIT = 20
_LIST_DISTRIBUTIONS_MAX_LIMIT = 100

logger = logging.getLogger(__name__)


class AssetMutationError(Exception):
    """Domain rule violation when persisting or mutating an asset (not request shape)."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


class DistributionMutationError(Exception):
    """Domain rule violation when creating a distribution."""

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
        resolved_family_id = family_id
        if resolved_family_id is None:
            membership = FamilyMembership.objects.filter(user_id=user_id).first()
            if membership is None:
                raise AssetMutationError(
                    "Not in a family; join or create a family first.",
                    status_code=400,
                )
            resolved_family_id = membership.family_id
        try:
            fam = Family.objects.get(pk=resolved_family_id)
        except Family.DoesNotExist as exc:
            raise AssetMutationError("Family not found.", status_code=404) from exc
        if not FamilyMembership.objects.filter(
            family_id=fam.pk,
            user_id=user_id,
        ).exists():
            raise AssetMutationError(
                "Not a member of this family.",
                status_code=403,
            )

    emoji = ""
    try:
        emoji = gemini_service.suggest_asset_emoji(name=name)
    except RuntimeError:
        logger.warning(
            "Skipped Gemini asset emoji: GEMINI_API_KEY not set (asset name=%r).",
            name[:80],
        )
    except Exception:
        logger.exception(
            "Gemini asset emoji failed for create name=%r",
            name[:80],
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
                emoji=emoji,
            )
    except IntegrityError as exc:
        raise AssetMutationError(
            "An asset with this name already exists in this scope.",
            status_code=409,
        ) from exc

    return row.pk


def list_assets(*, user_id: int, scope: str) -> list[Asset]:
    """List assets for the given savings scope (caller validates ``scope``)."""
    if scope == SavingsScope.PERSONAL:
        qs = Asset.objects.filter(
            owner_id=user_id,
            scope=SavingsScope.PERSONAL,
        ).order_by("name", "id")
        return list(qs)

    membership = FamilyMembership.objects.filter(user_id=user_id).first()
    if membership is None:
        return []
    fid = membership.family_id
    qs = Asset.objects.filter(
        scope=SavingsScope.FAMILY,
        family_id=fid,
    ).order_by("name", "id")
    return list(qs)


def list_distributions(
    *,
    user_id: int,
    scope: str,
    limit: int = _LIST_DISTRIBUTIONS_DEFAULT_LIMIT,
    offset: int = 0,
) -> list[Distribution]:
    """List distributions for scope with lines prefetched (newest first); paginated slice."""
    lim = max(1, min(int(limit), _LIST_DISTRIBUTIONS_MAX_LIMIT))
    off = max(0, int(offset))
    if scope == SavingsScope.PERSONAL:
        qs = (
            Distribution.objects.filter(
                owner_id=user_id,
                scope=SavingsScope.PERSONAL,
            )
            .prefetch_related("lines")
            .order_by("-created_at", "-id")
        )
        return list(qs[off : off + lim])

    membership = FamilyMembership.objects.filter(user_id=user_id).first()
    if membership is None:
        return []
    qs = (
        Distribution.objects.filter(
            scope=SavingsScope.FAMILY,
            family_id=membership.family_id,
        )
        .prefetch_related("lines")
        .order_by("-created_at", "-id")
    )
    return list(qs[off : off + lim])


def get_distribution_for_user(
    *, user_id: int, distribution_id: int
) -> Distribution | None:
    """Return distribution if ``user_id`` may read it (same rules as ``list_distributions``)."""
    personal = Distribution.objects.filter(
        pk=distribution_id,
        owner_id=user_id,
        scope=SavingsScope.PERSONAL,
    ).first()
    if personal is not None:
        return personal

    membership = FamilyMembership.objects.filter(user_id=user_id).first()
    if membership is None:
        return None
    return Distribution.objects.filter(
        pk=distribution_id,
        scope=SavingsScope.FAMILY,
        family_id=membership.family_id,
    ).first()


def update_distribution_notes(
    *, user_id: int, distribution_id: int, notes: str
) -> None:
    """Set ``notes`` on distribution; caller validates payload."""
    dist = get_distribution_for_user(
        user_id=user_id, distribution_id=distribution_id
    )
    if dist is None:
        raise DistributionMutationError("Distribution not found.", status_code=404)
    dist.notes = notes
    dist.save(update_fields=("notes",))


def get_asset_for_user(*, user_id: int, asset_id: int) -> Asset | None:
    """Return asset row if ``user_id`` may read it (same rules as ``list_assets``)."""
    personal = Asset.objects.filter(
        pk=asset_id,
        owner_id=user_id,
        scope=SavingsScope.PERSONAL,
    ).first()
    if personal is not None:
        return personal

    membership = FamilyMembership.objects.filter(user_id=user_id).first()
    if membership is None:
        return None
    return Asset.objects.filter(
        pk=asset_id,
        scope=SavingsScope.FAMILY,
        family_id=membership.family_id,
    ).first()


def update_asset(
    *,
    user_id: int,
    asset_id: int,
    name: str,
    weight: Decimal,
    current_amount: Decimal,
    target_amount: Decimal | None,
    currency: str,
) -> Asset:
    """Update mutable fields; caller validates payload (e.g. ``UpdateAssetRequest``)."""
    row = get_asset_for_user(user_id=user_id, asset_id=asset_id)
    if row is None:
        raise AssetMutationError("Asset not found.", status_code=404)

    old_name = row.name
    row.name = name
    row.weight = weight
    if target_amount is not None and target_amount < current_amount:
        raise AssetMutationError(
            "Target amount cannot be below current amount.",
            status_code=400,
        )
    row.current_amount = current_amount
    row.target_amount = target_amount
    row.currency = currency

    if name != old_name:
        try:
            row.emoji = gemini_service.suggest_asset_emoji(name=name)
        except RuntimeError:
            logger.warning(
                "Skipped Gemini asset emoji: GEMINI_API_KEY not set (update asset id=%s).",
                asset_id,
            )
        except Exception:
            logger.exception(
                "Gemini asset emoji failed on update for asset id=%s",
                asset_id,
            )

    update_fields = (
        "name",
        "weight",
        "current_amount",
        "target_amount",
        "currency",
        "updated_at",
    )
    if name != old_name:
        update_fields = update_fields + ("emoji",)

    try:
        row.save(
            update_fields=update_fields,
        )
    except IntegrityError as exc:
        raise AssetMutationError(
            "An asset with this name already exists in this scope.",
            status_code=409,
        ) from exc

    return row


def _integer_split_by_weights(total_units: int, weights: list[Decimal]) -> list[int]:
    """Split ``total_units`` across ``weights`` using Hamilton largest remainder."""
    n = len(weights)
    total_w = sum(weights, Decimal("0"))
    exact = [Decimal(total_units) * (weights[i] / total_w) for i in range(n)]
    floors = [
        int(e.quantize(Decimal("1"), rounding=ROUND_DOWN)) for e in exact
    ]
    allocated = sum(floors)
    remainder = total_units - allocated
    frac_order = sorted(
        range(n),
        key=lambda i: (exact[i] - Decimal(floors[i]), -i),
        reverse=True,
    )
    out = floors[:]
    for k in range(remainder):
        out[frac_order[k]] += 1
    return out


def _min_currency_step(currency: str) -> Decimal:
    """Smallest positive amount unit for quantize (CLP: 1 peso; else cents)."""
    return Decimal("1") if currency == "CLP" else Decimal("0.01")


def _receive_headroom(asset: Asset, allocated_so_far: Decimal) -> Decimal | None:
    """Room for additional **positive** allocation without crossing ``target_amount``.

    ``None`` means no cap. ``Decimal('0')`` means already at or over target.
    ``allocated_so_far`` is cumulative planned credit for this distribution (dry run or txn).
    """
    if asset.target_amount is None:
        return None
    gap = asset.target_amount - asset.current_amount - allocated_so_far
    return gap if gap > 0 else Decimal("0")


def _allocate_budget_respecting_targets(
    budget_amount: Decimal,
    resolved_assets: list[Asset],
    currency: str,
) -> list[Decimal]:
    """Pro-rata split with iterative cap when ``target_amount`` would be exceeded.

    Positive ``budget_amount``: rounds of weighted split; each line capped by headroom to
    target; uncapped lines absorb remainder until budget exhausted or no asset can take more.

    Non-positive ``budget_amount``: same as single ``_split_budget_by_weights`` (no target cap).

    Returns per-asset amounts in ``resolved_assets`` order; sum may be less than
    ``budget_amount`` when all targets saturated before budget depleted.
    """
    n = len(resolved_assets)
    if n == 0:
        return []

    if budget_amount <= 0:
        weights = [a.weight for a in resolved_assets]
        return _split_budget_by_weights(budget_amount, weights, currency)

    q = _min_currency_step(currency)
    allocated: list[Decimal] = [Decimal("0")] * n
    remaining = budget_amount
    max_iters = max(32, n * 24 + 8)

    for _ in range(max_iters):
        if remaining <= 0:
            break
        active_idx: list[int] = []
        for i, a in enumerate(resolved_assets):
            hr = _receive_headroom(a, allocated[i])
            if hr is None or hr > 0:
                active_idx.append(i)
        if not active_idx:
            break
        weights = [resolved_assets[i].weight for i in active_idx]
        chunk = _split_budget_by_weights(remaining, weights, currency)
        moved = Decimal("0")
        for j, i in enumerate(active_idx):
            raw = chunk[j]
            if raw <= 0:
                continue
            hr = _receive_headroom(resolved_assets[i], allocated[i])
            if hr is None:
                take = raw
            else:
                take = min(raw, hr)
            take = take.quantize(q)
            if take <= 0:
                continue
            allocated[i] += take
            moved += take
        if moved <= 0:
            break
        remaining -= moved

    return allocated


def _split_budget_by_weights(
    budget_amount: Decimal,
    weights: list[Decimal],
    currency: str,
) -> list[Decimal]:
    """Pro-rata split by weights. CLP: whole pesos; other ISO currencies: hundredths."""
    if not weights:
        raise DistributionMutationError(
            "At least one asset is required.",
            status_code=400,
        )
    total_w = sum(weights, Decimal("0"))
    if total_w <= 0:
        raise DistributionMutationError(
            "Combined weight of selected assets must be positive.",
            status_code=400,
        )

    sign = Decimal("1") if budget_amount >= 0 else Decimal("-1")
    abs_budget = abs(budget_amount)

    if currency == "CLP":
        if abs_budget != abs_budget.quantize(Decimal("1")):
            raise DistributionMutationError(
                "CLP amounts must be whole pesos (no decimals).",
                status_code=400,
            )
        units = int(abs_budget)
        ints = _integer_split_by_weights(units, weights)
        return [sign * Decimal(x) for x in ints]

    cents_total = int((abs_budget * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_DOWN))
    ints = _integer_split_by_weights(cents_total, weights)
    return [sign * (Decimal(x) / Decimal("100")) for x in ints]


def delete_asset(*, user_id: int, asset_id: int) -> None:
    """Delete asset if visible to user; removes its distribution lines and fixes budgets."""
    row = get_asset_for_user(user_id=user_id, asset_id=asset_id)
    if row is None:
        raise AssetMutationError("Asset not found.", status_code=404)
    with transaction.atomic():
        touched_distribution_ids = list(
            DistributionLine.objects.filter(asset_id=row.pk)
            .values_list("distribution_id", flat=True)
            .distinct()
        )
        DistributionLine.objects.filter(asset_id=row.pk).delete()
        for did in touched_distribution_ids:
            total = DistributionLine.objects.filter(distribution_id=did).aggregate(
                s=Sum("allocated_amount")
            )["s"]
            if total is None:
                total = Decimal("0")
            Distribution.objects.filter(pk=did).update(budget_amount=total)
        row.delete()


def _resolve_assets_for_distribution(
    *,
    user_id: int,
    scope: str,
    currency: str,
    family_id: int | None,
    asset_ids: list[int],
) -> tuple[Family | None, list[Asset]]:
    """Validate scope/family membership and assets; return family (if any) and rows in ``asset_ids`` order."""
    if scope == SavingsScope.PERSONAL:
        fam = None
    else:
        try:
            fam = Family.objects.get(pk=family_id)
        except Family.DoesNotExist as exc:
            raise DistributionMutationError("Family not found.", status_code=404) from exc
        if not FamilyMembership.objects.filter(
            family_id=fam.pk,
            user_id=user_id,
        ).exists():
            raise DistributionMutationError(
                "Not a member of this family.",
                status_code=403,
            )

    if not asset_ids:
        raise DistributionMutationError(
            "At least one asset is required.",
            status_code=400,
        )

    if len(asset_ids) != len(set(asset_ids)):
        raise DistributionMutationError(
            "Duplicate asset in asset_ids.",
            status_code=400,
        )

    resolved_assets: list[Asset] = []
    for asset_id in asset_ids:
        row = get_asset_for_user(user_id=user_id, asset_id=asset_id)
        if row is None:
            raise DistributionMutationError("Asset not found.", status_code=404)
        if row.scope != scope:
            raise DistributionMutationError(
                "Asset scope does not match distribution scope.",
                status_code=400,
            )
        if scope == SavingsScope.FAMILY:
            assert fam is not None
            if row.family_id != fam.pk:
                raise DistributionMutationError(
                    "Asset does not belong to this family.",
                    status_code=400,
                )
        if row.currency != currency:
            raise DistributionMutationError(
                "All assets must use the same currency as the distribution.",
                status_code=400,
            )
        resolved_assets.append(row)

    return fam, resolved_assets


def simulate_distribution(
    *,
    user_id: int,
    scope: str,
    budget_amount: Decimal,
    currency: str,
    family_id: int | None,
    asset_ids: list[int],
) -> list[tuple[int, Decimal]]:
    """Compute splits without persisting. Same cap-and-redistribute rules as ``create_distribution``."""
    _, resolved_assets = _resolve_assets_for_distribution(
        user_id=user_id,
        scope=scope,
        currency=currency,
        family_id=family_id,
        asset_ids=asset_ids,
    )
    allocated_amounts = _allocate_budget_respecting_targets(
        budget_amount, resolved_assets, currency
    )
    return [
        (asset_row.pk, amt)
        for asset_row, amt in zip(resolved_assets, allocated_amounts, strict=True)
    ]


def create_distribution(
    *,
    user_id: int,
    scope: str,
    budget_amount: Decimal,
    currency: str,
    family_id: int | None,
    asset_ids: list[int],
    notes: str = "",
) -> int:
    """Persist distribution, lines, and bump asset balances.

    Positive ``budget_amount``: weighted split with per-line cap up to ``target_amount``;
    leftover budget flows to assets still below target. ``Distribution.budget_amount`` is
    sum of line allocations (may be less than requested if targets saturate first).
    Non-positive ``budget_amount``: unchanged single-pass weighted split.
    """
    fam, _ = _resolve_assets_for_distribution(
        user_id=user_id,
        scope=scope,
        currency=currency,
        family_id=family_id,
        asset_ids=asset_ids,
    )

    with transaction.atomic():
        locked_by_pk = {
            a.pk: a
            for a in Asset.objects.select_for_update().filter(
                pk__in=asset_ids,
            ).order_by("pk")
        }
        if len(locked_by_pk) != len(asset_ids):
            raise DistributionMutationError("Asset not found.", status_code=404)
        locked_assets = [locked_by_pk[aid] for aid in asset_ids]

        allocated_amounts = _allocate_budget_respecting_targets(
            budget_amount, locked_assets, currency
        )
        total_allocated = sum(allocated_amounts, Decimal("0"))
        if budget_amount > 0 and total_allocated <= 0:
            raise DistributionMutationError(
                "No room to allocate toward selected assets (all at or above target).",
                status_code=400,
            )

        dist = Distribution.objects.create(
            owner_id=user_id,
            scope=scope,
            family=fam,
            budget_amount=total_allocated,
            currency=currency,
            notes=notes,
        )
        for asset_row, amt in zip(locked_assets, allocated_amounts, strict=True):
            DistributionLine.objects.create(
                distribution=dist,
                asset=asset_row,
                allocated_amount=amt,
            )
            asset_row.current_amount += amt
            asset_row.save(update_fields=("current_amount", "updated_at"))

    return dist.pk


def _list_peer_assets_for_rush(*, user_id: int, beneficiary: Asset) -> list[Asset]:
    """Same visibility as ``list_assets``, excluding ``beneficiary``."""
    rows = list_assets(user_id=user_id, scope=beneficiary.scope)
    return [a for a in rows if a.pk != beneficiary.pk]


def _rush_donor_capacity(asset: Asset) -> Decimal:
    """Max amount rush may pull from this donor: full ``current_amount``.

    Rush ignores donor ``target_amount``; weights split the gap among drawable balances.
    """
    return asset.current_amount


def _compute_rush_transfers(
    *, user_id: int, beneficiary_asset_id: int
) -> tuple[Asset, str, Decimal, dict[int, Decimal]]:
    """Shared plan for rush: beneficiary row, currency, inflow amount, donor id -> negative delta."""
    beneficiary = get_asset_for_user(user_id=user_id, asset_id=beneficiary_asset_id)
    if beneficiary is None:
        raise DistributionMutationError("Asset not found.", status_code=404)

    if beneficiary.target_amount is None:
        raise DistributionMutationError(
            "Asset has no target amount; nothing to rush toward.",
            status_code=400,
        )

    gap = beneficiary.target_amount - beneficiary.current_amount
    if gap <= 0:
        raise DistributionMutationError(
            "Asset already meets or exceeds its target.",
            status_code=400,
        )

    peers = _list_peer_assets_for_rush(user_id=user_id, beneficiary=beneficiary)
    currency = beneficiary.currency

    # Donors: positive balance; same currency only. Targets on donors not enforced.
    donors: list[Asset] = []
    for a in peers:
        if a.currency != currency:
            continue
        if _rush_donor_capacity(a) <= 0:
            continue
        donors.append(a)

    if not donors:
        raise DistributionMutationError(
            "No other assets in this scope can contribute toward the target.",
            status_code=400,
        )

    donor_remaining: dict[int, Decimal] = {
        a.pk: _rush_donor_capacity(a) for a in donors
    }

    transfers: dict[int, Decimal] = {}

    def add_transfer(asset_id: int, delta: Decimal) -> None:
        transfers[asset_id] = transfers.get(asset_id, Decimal("0")) + delta

    remaining_gap = gap
    max_iters = max(32, len(donors) * 24 + 8)
    for _ in range(max_iters):
        if remaining_gap <= 0:
            break
        active: list[Asset] = []
        for a in donors:
            cap = donor_remaining[a.pk]
            if cap > 0:
                active.append(a)
        if not active:
            break
        weights = [a.weight for a in active]
        if sum(weights, Decimal("0")) <= 0:
            raise DistributionMutationError(
                "Combined weight of contributing assets must be positive.",
                status_code=400,
            )
        chunk_amounts = _split_budget_by_weights(remaining_gap, weights, currency)
        moved_this_round = Decimal("0")
        for asset_row, raw_amt in zip(active, chunk_amounts, strict=True):
            if raw_amt <= 0:
                continue
            cap = donor_remaining[asset_row.pk]
            take = min(raw_amt, cap)
            if take <= 0:
                continue
            q = Decimal("1") if currency == "CLP" else Decimal("0.01")
            take = take.quantize(q)
            add_transfer(asset_row.pk, -take)
            moved_this_round += take
            donor_remaining[asset_row.pk] = cap - take
        if moved_this_round <= 0:
            break
        remaining_gap -= moved_this_round

    total_to_beneficiary = gap - remaining_gap
    if total_to_beneficiary <= 0:
        raise DistributionMutationError(
            "Insufficient balance in other assets to rush this target.",
            status_code=400,
        )

    return beneficiary, currency, total_to_beneficiary, transfers


def simulate_rush_asset(
    *, user_id: int, beneficiary_asset_id: int
) -> list[tuple[int, Decimal]]:
    """Preview rush lines (beneficiary positive, donors negative); no DB writes."""
    beneficiary, _currency, total_to_beneficiary, transfers = _compute_rush_transfers(
        user_id=user_id,
        beneficiary_asset_id=beneficiary_asset_id,
    )
    lines: list[tuple[int, Decimal]] = [
        (beneficiary.pk, total_to_beneficiary),
    ]
    for asset_id in sorted(transfers.keys()):
        delta = transfers[asset_id]
        if delta != 0:
            lines.append((asset_id, delta))
    return lines


def rush_asset(*, user_id: int, beneficiary_asset_id: int) -> tuple[int, Asset]:
    """Move pooled balance from other assets in same scope onto beneficiary.

    Repeatedly splits remaining gap to target using donor weights; each donor capped by
    ``current_amount`` only (donor targets ignored).
    Persists one ``Distribution`` and signed ``DistributionLine`` rows (positive line on
    beneficiary, negatives on donors; net zero). ``budget_amount`` is ``0`` — rush is an
    internal rebalance, not new capital into the scope.
    """
    beneficiary, currency, total_to_beneficiary, transfers = _compute_rush_transfers(
        user_id=user_id,
        beneficiary_asset_id=beneficiary_asset_id,
    )

    with transaction.atomic():
        beneficiary_locked = Asset.objects.select_for_update().get(pk=beneficiary.pk)
        rush_notes = (
            f'Rush toward target for "{beneficiary_locked.name}" '
            f"(asset_id={beneficiary_locked.pk})"
        )
        dist = Distribution.objects.create(
            owner_id=user_id,
            scope=beneficiary_locked.scope,
            family=beneficiary_locked.family,
            budget_amount=Decimal("0"),
            currency=currency,
            notes=rush_notes,
        )
        DistributionLine.objects.create(
            distribution=dist,
            asset=beneficiary_locked,
            allocated_amount=total_to_beneficiary,
        )
        for asset_id in sorted(transfers.keys()):
            delta = transfers[asset_id]
            if delta == 0:
                continue
            donor_row = Asset.objects.select_for_update().get(pk=asset_id)
            DistributionLine.objects.create(
                distribution=dist,
                asset=donor_row,
                allocated_amount=delta,
            )
            donor_row.current_amount += delta
            donor_row.save(update_fields=("current_amount", "updated_at"))
        beneficiary_locked.current_amount += total_to_beneficiary
        beneficiary_locked.save(update_fields=("current_amount", "updated_at"))

    beneficiary_locked.refresh_from_db()
    return dist.pk, beneficiary_locked
