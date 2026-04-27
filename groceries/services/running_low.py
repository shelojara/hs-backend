import logging
from datetime import datetime

from django.contrib.auth import get_user_model
from django.utils import timezone

from backend.email_services import send_email_via_gmail
from groceries import gemini_service
from groceries.gemini_service import RunningLowSuggestion
from groceries.models import Basket, Product

from .baskets import list_purchased_baskets_for_running_low

logger = logging.getLogger(__name__)


def _format_purchased_baskets_for_running_low(
    baskets: list[Basket],
    *,
    omit_snoozed_after: datetime | None = None,
) -> str:
    """Build plain-text block of basket history for Gemini (newest first).

    When *omit_snoozed_after* is set, lines for products with
    ``running_low_snoozed_until`` strictly after that instant are omitted (not sent
    to Gemini). Basket sections are renumbered to include only baskets with at
    least one visible line.
    """
    lines: list[str] = []
    out_bi = 0
    for basket in baskets:
        raw = list(basket.products.all())
        if omit_snoozed_after is not None:
            products = [
                p
                for p in raw
                if not (
                    p.running_low_snoozed_until is not None
                    and p.running_low_snoozed_until > omit_snoozed_after
                )
            ]
        else:
            products = raw
        if not products:
            continue
        out_bi += 1
        ts = basket.purchased_at
        ts_label = ts.isoformat() if ts else ""
        lines.append(f"## Basket {out_bi} (purchased_at: {ts_label})")
        for p in products:
            fmt = (p.format or "").strip()
            em = (p.emoji or "").strip()
            name = (p.name or "").strip()
            bit = f"- [product_id={p.pk}] {em + ' ' if em else ''}{name}"
            if fmt:
                bit += f" — {fmt}"
            lines.append(bit)
        lines.append("")
    return "\n".join(lines).strip()


def _running_low_report_recipient_emails(*, user_id: int) -> list[str]:
    """Distinct non-blank emails for *user_id* when user active (stable order)."""
    User = get_user_model()
    ordered: list[str] = []
    seen: set[str] = set()
    qs = (
        User.objects.filter(pk=user_id, is_active=True)
        .exclude(email__isnull=True)
        .exclude(email="")
        .order_by("id")
        .values_list("email", flat=True)
    )
    for raw in qs:
        addr = str(raw).strip()
        if addr and addr not in seen:
            seen.add(addr)
            ordered.append(addr)
    return ordered


def _format_running_low_digest_email_body(
    *,
    still_low: list[Product],
    newly_low: list[Product],
    pid_to_suggestion: dict[int, RunningLowSuggestion],
) -> str:
    def line_for(p: Product) -> str:
        em = (p.emoji or "").strip()
        name = (p.name or "").strip()
        fmt = (p.format or "").strip()
        bit = f"- [product_id={p.pk}] {em + ' ' if em else ''}{name}"
        if fmt:
            bit += f" — {fmt}"
        sug = pid_to_suggestion.get(p.pk)
        if sug is not None and (sug.reason or "").strip():
            bit += f"\n  {sug.reason.strip()}"
        return bit

    parts = [
        "Groceries — products running low",
        "",
        "Still running low (from before this sync):",
    ]
    if still_low:
        parts.extend(line_for(p) for p in still_low)
    else:
        parts.append("(none)")
    parts.extend(["", "Newly flagged this sync:"])
    if newly_low:
        parts.extend(line_for(p) for p in newly_low)
    else:
        parts.append("(none)")
    return "\n".join(parts)


def _send_running_low_digest_email(
    *,
    user_id: int,
    still_low: list[Product],
    newly_low: list[Product],
    pid_to_suggestion: dict[int, RunningLowSuggestion],
) -> None:
    recipients = _running_low_report_recipient_emails(user_id=user_id)
    if not recipients:
        logger.warning(
            "Running-low digest not emailed: user id=%s has no email or inactive.",
            user_id,
        )
        return
    body = _format_running_low_digest_email_body(
        still_low=still_low,
        newly_low=newly_low,
        pid_to_suggestion=pid_to_suggestion,
    )
    subject = "Groceries: products running low"
    try:
        send_email_via_gmail(to_addrs=recipients, subject=subject, body=body)
    except Exception:
        logger.exception("Running-low digest email failed for user id=%s", user_id)


def sync_running_low_flags_for_user(*, user_id: int) -> None:
    """Set ``Product.running_low`` from Gemini, using purchases from last two months.

    Clears ``running_low`` for all of the user's products first. Snoozed products
    (``running_low_snoozed_until`` after *now*) are omitted from the history text
    sent to Gemini. Suggested ids for snoozed rows are still ignored when applying
    updates (defense in depth). After a successful sync that flags at least one
    product, emails the user a digest (still low vs newly flagged).
    """
    now = timezone.now()
    before_running_low_ids = set(
        Product.objects.filter(user_id=user_id, running_low=True).values_list(
            "pk",
            flat=True,
        ),
    )
    Product.objects.filter(user_id=user_id).update(running_low=False)
    baskets = list_purchased_baskets_for_running_low(user_id=user_id)
    baskets = [b for b in baskets if list(b.products.all())]
    if not baskets:
        return
    block = _format_purchased_baskets_for_running_low(
        baskets,
        omit_snoozed_after=now,
    )
    if not block:
        return
    try:
        suggestions = gemini_service.suggest_running_low_from_purchase_history(
            history_markdown=block,
        )
    except RuntimeError:
        logger.warning(
            "Skipped Gemini running-low sync: GEMINI_API_KEY not set (user id=%s).",
            user_id,
        )
        return
    except Exception:
        logger.exception(
            "Gemini running-low sync failed for user id=%s",
            user_id,
        )
        return
    pids: set[int] = set()
    for s in suggestions:
        for pid in s.product_ids:
            if pid > 0:
                pids.add(pid)
    if not pids:
        return
    eligible = Product.objects.filter(user_id=user_id, pk__in=pids).exclude(
        running_low_snoozed_until__gt=now,
    )
    final_running_low_ids = set(eligible.values_list("pk", flat=True))
    if not final_running_low_ids:
        return
    pid_to_suggestion: dict[int, RunningLowSuggestion] = {}
    for s in suggestions:
        for pid in s.product_ids:
            if pid > 0 and pid not in pid_to_suggestion:
                pid_to_suggestion[pid] = s
    eligible.update(running_low=True)
    still_ids = sorted(before_running_low_ids & final_running_low_ids)
    new_ids = sorted(final_running_low_ids - before_running_low_ids)
    still_low = list(Product.objects.filter(pk__in=still_ids).order_by("name", "pk"))
    newly_low = list(Product.objects.filter(pk__in=new_ids).order_by("name", "pk"))
    _send_running_low_digest_email(
        user_id=user_id,
        still_low=still_low,
        newly_low=newly_low,
        pid_to_suggestion=pid_to_suggestion,
    )
