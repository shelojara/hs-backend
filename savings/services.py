"""Business logic for savings app."""

import logging
from dataclasses import dataclass
from datetime import date, datetime, time as dt_time
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from typing import Protocol

from django.db import IntegrityError, transaction
from django.db.models import Case, Count, DecimalField, F, Q, Sum, Value, When
from django.db.models.functions import Least
from django.utils import timezone

from savings import gemini_service
from savings.models import (
    Asset,
    AssetState,
    Distribution,
    DistributionLine,
    Family,
    FamilyMembership,
    SavingsScope,
)

_LIST_DISTRIBUTIONS_DEFAULT_LIMIT = 20
_LIST_DISTRIBUTIONS_MAX_LIMIT = 100

logger = logging.getLogger(__name__)


@dataclass
class _SplitTargetView:
    """Minimal row for ``_allocate_budget_respecting_targets`` (weight + balances)."""

    weight: Decimal
    current_amount: Decimal
    target_amount: Decimal | None


class _SupportsAllocationSplit(Protocol):
    weight: Decimal
    current_amount: Decimal
    target_amount: Decimal | None


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


def _family_for_user(user_id: int) -> Family | None:
    """User has at most one family membership."""
    m = FamilyMembership.objects.filter(user_id=user_id).first()
    return m.family if m is not None else None


def create_asset(
    *,
    user_id: int,
    scope: str,
    name: str,
    weight: Decimal,
    current_amount: Decimal,
    target_amount: Decimal | None,
    currency: str,
) -> int:
    """Create asset for authenticated user. Returns new asset primary key.

    Caller must pass values already validated (e.g. from ``CreateAssetRequest``).
    """
    if scope == SavingsScope.PERSONAL:
        fam = None
    else:
        fam = _family_for_user(user_id)
        if fam is None:
            raise AssetMutationError(
                "Family scope requires family membership.",
                status_code=400,
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


def _asset_completion_ratio(asset: Asset) -> Decimal:
    """Fraction toward target (0..1) for ordering active assets; no target → 0."""
    if asset.target_amount is None or asset.target_amount <= 0:
        return Decimal("0")
    if asset.current_amount <= 0:
        return Decimal("0")
    raw = asset.current_amount / asset.target_amount
    if raw >= 1:
        return Decimal("1")
    return raw


def _list_assets_sort_key(asset: Asset) -> tuple:
    """Completed last; active descending by completion ratio, then name, id."""
    if asset.state == AssetState.COMPLETED:
        return (1, asset.name, asset.pk)
    ratio = _asset_completion_ratio(asset)
    return (0, -ratio, asset.name, asset.pk)


def list_assets(
    *,
    user_id: int,
    scope: str,
    state: str | None = None,
) -> list[Asset]:
    """List assets for the given savings scope (caller validates ``scope``)."""
    if scope == SavingsScope.PERSONAL:
        qs = Asset.objects.filter(
            owner_id=user_id,
            scope=SavingsScope.PERSONAL,
        )
        if state is not None:
            qs = qs.filter(state=state)
        rows = list(qs)
        rows.sort(key=_list_assets_sort_key)
        return rows

    membership = FamilyMembership.objects.filter(user_id=user_id).first()
    if membership is None:
        return []
    fid = membership.family_id
    qs = Asset.objects.filter(
        scope=SavingsScope.FAMILY,
        family_id=fid,
    )
    if state is not None:
        qs = qs.filter(state=state)
    rows = list(qs)
    rows.sort(key=_list_assets_sort_key)
    return rows


@dataclass(frozen=True)
class SavingsStatistics:
    """Aggregates for one scope (same visibility rules as ``list_assets`` / ``list_distributions``)."""

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


def _distributions_base_qs(*, user_id: int, scope: str):
    """Queryset of distributions visible to ``user_id`` in ``scope`` (no ordering)."""
    if scope == SavingsScope.PERSONAL:
        return Distribution.objects.filter(
            owner_id=user_id,
            scope=SavingsScope.PERSONAL,
        )
    membership = FamilyMembership.objects.filter(user_id=user_id).first()
    if membership is None:
        return Distribution.objects.none()
    return Distribution.objects.filter(
        scope=SavingsScope.FAMILY,
        family_id=membership.family_id,
    )


def _assets_base_qs(*, user_id: int, scope: str):
    """Queryset of assets visible to ``user_id`` in ``scope``."""
    if scope == SavingsScope.PERSONAL:
        return Asset.objects.filter(
            owner_id=user_id,
            scope=SavingsScope.PERSONAL,
        )
    membership = FamilyMembership.objects.filter(user_id=user_id).first()
    if membership is None:
        return Asset.objects.none()
    return Asset.objects.filter(
        scope=SavingsScope.FAMILY,
        family_id=membership.family_id,
    )


def _calendar_month_bounds_local() -> tuple[datetime, datetime]:
    """Start of local calendar month and start of next month (exclusive end), timezone-aware."""
    tz = timezone.get_current_timezone()
    today = timezone.localdate()
    start_local = datetime.combine(
        date(today.year, today.month, 1),
        dt_time.min,
        tzinfo=tz,
    )
    if today.month == 12:
        end_local = datetime.combine(
            date(today.year + 1, 1, 1),
            dt_time.min,
            tzinfo=tz,
        )
    else:
        end_local = datetime.combine(
            date(today.year, today.month + 1, 1),
            dt_time.min,
            tzinfo=tz,
        )
    return start_local, end_local


def get_statistics(*, user_id: int, scope: str) -> SavingsStatistics:
    """Rollups for current local month and lifetime completion counts."""
    start, end_excl = _calendar_month_bounds_local()
    dist_qs = _distributions_base_qs(user_id=user_id, scope=scope)
    in_month = dist_qs.filter(created_at__gte=start, created_at__lt=end_excl)
    month_row = in_month.aggregate(
        c=Count("id"),
        net=Sum("budget_amount"),
    )
    dist_count = int(month_row["c"] or 0)
    net_budget = month_row["net"] or Decimal("0")

    pos_sum = (
        DistributionLine.objects.filter(
            distribution__in=in_month,
            allocated_amount__gt=0,
        ).aggregate(s=Sum("allocated_amount"))["s"]
        or Decimal("0")
    )

    assets_qs = _assets_base_qs(user_id=user_id, scope=scope)
    completed = assets_qs.filter(state=AssetState.COMPLETED).count()
    active = assets_qs.filter(state=AssetState.ACTIVE).count()
    total = assets_qs.count()

    dec_out = DecimalField(max_digits=24, decimal_places=2)
    progress_row = assets_qs.aggregate(
        total_target=Sum(
            Case(
                When(
                    Q(target_amount__isnull=True) | Q(target_amount__lte=0),
                    then=Value(Decimal("0")),
                ),
                default=F("target_amount"),
                output_field=dec_out,
            )
        ),
        total_saved=Sum(
            Case(
                When(
                    state=AssetState.COMPLETED,
                    target_amount__isnull=False,
                    target_amount__gt=0,
                    then=F("target_amount"),
                ),
                When(
                    Q(target_amount__isnull=False) & Q(target_amount__gt=0),
                    then=Least(F("current_amount"), F("target_amount")),
                ),
                default=Value(Decimal("0")),
                output_field=dec_out,
            )
        ),
    )
    sum_target = progress_row["total_target"] or Decimal("0")
    sum_saved = progress_row["total_saved"] or Decimal("0")
    if sum_target > 0:
        scope_pct = (sum_saved / sum_target * Decimal("100")).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )
    else:
        scope_pct = Decimal("0")

    return SavingsStatistics(
        period_month_start=start,
        period_month_end_exclusive=end_excl,
        distributions_count_this_month=dist_count,
        distributions_net_budget_this_month=net_budget,
        positive_allocations_sum_this_month=pos_sum,
        targets_hit_all_time=completed,
        active_assets_count=active,
        completed_assets_count=completed,
        assets_total_count=total,
        scope_overall_progress_percent=scope_pct,
    )


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
    qs = (
        _distributions_base_qs(user_id=user_id, scope=scope)
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


def set_asset_completion(
    *, user_id: int, asset_id: int, completed: bool
) -> Asset:
    """Mark asset ACTIVE or COMPLETED (completed excluded from distributions and rush)."""
    row = get_asset_for_user(user_id=user_id, asset_id=asset_id)
    if row is None:
        raise AssetMutationError("Asset not found.", status_code=404)
    if completed:
        row.state = AssetState.COMPLETED
        row.completed_at = timezone.now()
    else:
        row.state = AssetState.ACTIVE
        row.completed_at = None
    row.save(update_fields=("state", "completed_at", "updated_at"))
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


def _receive_headroom(
    asset: _SupportsAllocationSplit, allocated_so_far: Decimal
) -> Decimal | None:
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
    resolved_assets: list[_SupportsAllocationSplit],
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


def _list_peer_assets_for_balance_on_delete(
    *, user_id: int, victim: Asset
) -> list[int]:
    """Other ACTIVE assets in same scope/currency as ``victim`` (excludes ``victim``)."""
    if victim.scope == SavingsScope.PERSONAL:
        qs = Asset.objects.filter(
            owner_id=user_id,
            scope=SavingsScope.PERSONAL,
            currency=victim.currency,
            state=AssetState.ACTIVE,
        ).exclude(pk=victim.pk)
    else:
        assert victim.family_id is not None
        qs = Asset.objects.filter(
            scope=SavingsScope.FAMILY,
            family_id=victim.family_id,
            currency=victim.currency,
            state=AssetState.ACTIVE,
        ).exclude(pk=victim.pk)
    return list(qs.values_list("pk", flat=True))


def delete_asset(*, user_id: int, asset_id: int) -> None:
    """Delete asset if visible to user.

    Non-zero ``current_amount``: normally ``create_distribution`` to peers (same rules as
    manual distributions). Peers with combined weight ≤ 0 use equal-weight split via same
    persist path as ``create_distribution``. ``DistributionMutationError`` from allocation
    becomes ``AssetMutationError`` so API stays 4xx on delete. No peers → balance discarded.
    """
    row = get_asset_for_user(user_id=user_id, asset_id=asset_id)
    if row is None:
        raise AssetMutationError("Asset not found.", status_code=404)
    peer_ids = _list_peer_assets_for_balance_on_delete(user_id=user_id, victim=row)
    lock_ids = sorted({row.pk, *peer_ids})
    with transaction.atomic():
        locked = {
            a.pk: a
            for a in Asset.objects.select_for_update().filter(pk__in=lock_ids).order_by(
                "pk"
            )
        }
        victim_locked = locked[row.pk]
        amount = victim_locked.current_amount
        if amount != 0 and peer_ids:
            delete_notes = (
                f'Redistributed balance from deleted asset "{victim_locked.name}" '
                f"(asset_id={victim_locked.pk})"
            )
            peer_locked_sorted = [locked[pid] for pid in sorted(peer_ids)]
            total_w = sum((a.weight for a in peer_locked_sorted), Decimal("0"))
            try:
                if total_w > 0:
                    create_distribution(
                        user_id=user_id,
                        scope=victim_locked.scope,
                        budget_amount=amount,
                        currency=victim_locked.currency,
                        asset_ids=sorted(peer_ids),
                        notes=delete_notes,
                    )
                else:
                    stand_ins = [
                        _SplitTargetView(
                            weight=Decimal("1"),
                            current_amount=a.current_amount,
                            target_amount=a.target_amount,
                        )
                        for a in peer_locked_sorted
                    ]
                    allocated_amounts = _allocate_budget_respecting_targets(
                        amount, stand_ins, victim_locked.currency
                    )
                    total_allocated = sum(allocated_amounts, Decimal("0"))
                    if amount > 0 and total_allocated <= 0:
                        raise AssetMutationError(
                            "No room to allocate toward selected assets (all at or above target).",
                            status_code=400,
                        )
                    _persist_distribution_lines_and_balances(
                        user_id=user_id,
                        scope=victim_locked.scope,
                        family=victim_locked.family,
                        currency=victim_locked.currency,
                        notes=delete_notes,
                        locked_assets=peer_locked_sorted,
                        allocated_amounts=allocated_amounts,
                    )
            except DistributionMutationError as exc:
                raise AssetMutationError(str(exc), status_code=exc.status_code) from exc
        touched_distribution_ids = list(
            DistributionLine.objects.filter(asset_id=victim_locked.pk)
            .values_list("distribution_id", flat=True)
            .distinct()
        )
        DistributionLine.objects.filter(asset_id=victim_locked.pk).delete()
        for did in touched_distribution_ids:
            total = DistributionLine.objects.filter(distribution_id=did).aggregate(
                s=Sum("allocated_amount")
            )["s"]
            if total is None:
                total = Decimal("0")
            Distribution.objects.filter(pk=did).update(budget_amount=total)
        victim_locked.delete()


def _resolve_assets_for_distribution(
    *,
    user_id: int,
    scope: str,
    currency: str,
    asset_ids: list[int],
) -> tuple[Family | None, list[Asset]]:
    """Validate scope/family membership and assets; return family (if any) and rows in ``asset_ids`` order."""
    if scope == SavingsScope.PERSONAL:
        fam = None
    else:
        fam = _family_for_user(user_id)
        if fam is None:
            raise DistributionMutationError(
                "Family scope requires family membership.",
                status_code=400,
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
        if row.state == AssetState.COMPLETED:
            raise DistributionMutationError(
                "Completed assets cannot be included in distributions.",
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
    asset_ids: list[int],
) -> list[tuple[int, Decimal]]:
    """Compute splits without persisting.

    Uses ``_resolve_assets_for_distribution`` — same rules as ``create_distribution``,
    including rejection of COMPLETED assets (cannot receive split).
    """
    _, resolved_assets = _resolve_assets_for_distribution(
        user_id=user_id,
        scope=scope,
        currency=currency,
        asset_ids=asset_ids,
    )
    allocated_amounts = _allocate_budget_respecting_targets(
        budget_amount, resolved_assets, currency
    )
    return [
        (asset_row.pk, amt)
        for asset_row, amt in zip(resolved_assets, allocated_amounts, strict=True)
    ]


def _persist_distribution_lines_and_balances(
    *,
    user_id: int,
    scope: str,
    family: Family | None,
    currency: str,
    notes: str,
    locked_assets: list[Asset],
    allocated_amounts: list[Decimal],
) -> int:
    """Create ``Distribution`` + lines and credit ``locked_assets`` (caller holds locks)."""
    total_allocated = sum(allocated_amounts, Decimal("0"))
    dist = Distribution.objects.create(
        owner_id=user_id,
        scope=scope,
        family=family,
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


def create_distribution(
    *,
    user_id: int,
    scope: str,
    budget_amount: Decimal,
    currency: str,
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

        return _persist_distribution_lines_and_balances(
            user_id=user_id,
            scope=scope,
            family=fam,
            currency=currency,
            notes=notes,
            locked_assets=locked_assets,
            allocated_amounts=allocated_amounts,
        )


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

    if beneficiary.state == AssetState.COMPLETED:
        raise DistributionMutationError(
            "Completed assets cannot be rush beneficiaries.",
            status_code=400,
        )

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
        if a.state == AssetState.COMPLETED:
            continue
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
    """Preview rush lines (beneficiary positive, donors negative); no DB writes.

    Same plan as ``rush_asset`` via ``_compute_rush_transfers``: COMPLETED assets
    cannot be beneficiaries; COMPLETED peers are not donors.
    """
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
