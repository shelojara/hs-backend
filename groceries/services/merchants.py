from django.db.models import Max

from groceries.favicon_service import fetch_favicon_url, normalize_website_url
from groceries.gemini_service import PreferredMerchantContext
from groceries.models import Merchant


def preferred_merchant_context_for_user(user_id: int) -> list[PreferredMerchantContext]:
    rows = Merchant.objects.filter(user_id=user_id).order_by(
        "preference_order",
        "pk",
    )
    return [
        PreferredMerchantContext(name=m.name, website=m.website)
        for m in rows
    ]


def list_user_merchants(*, user_id: int) -> list[Merchant]:
    """Preferred merchants for *user_id*, ordered by preference (then pk)."""
    return list(
        Merchant.objects.filter(user_id=user_id).order_by("preference_order", "pk"),
    )


def create_user_merchant(*, user_id: int, name: str, website: str) -> Merchant:
    """Persist a merchant and resolve ``favicon_url`` from *website*."""
    label = name.strip()
    if not label:
        msg = "Merchant name must not be empty."
        raise ValueError(msg)
    normalized = normalize_website_url(website)
    fav = fetch_favicon_url(website) or ""
    agg = Merchant.objects.filter(user_id=user_id).aggregate(m=Max("preference_order"))
    next_order = (agg["m"] if agg["m"] is not None else -1) + 1
    return Merchant.objects.create(
        user_id=user_id,
        name=label,
        website=normalized,
        favicon_url=fav,
        preference_order=next_order,
    )


def update_user_merchant(
    *,
    user_id: int,
    merchant_id: int,
    name: str,
    website: str,
) -> Merchant:
    """Update merchant fields and refresh favicon when *website* changes."""
    label = name.strip()
    if not label:
        msg = "Merchant name must not be empty."
        raise ValueError(msg)
    merchant = Merchant.objects.get(pk=merchant_id, user_id=user_id)
    normalized = normalize_website_url(website)
    merchant.name = label
    merchant.website = normalized
    merchant.favicon_url = fetch_favicon_url(website) or ""
    merchant.save()
    return merchant


def delete_user_merchant(*, user_id: int, merchant_id: int) -> None:
    """Delete a merchant owned by *user_id*."""
    merchant = Merchant.objects.get(pk=merchant_id, user_id=user_id)
    merchant.delete()
