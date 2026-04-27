import logging
from decimal import Decimal
from typing import Any

from django.utils import timezone
from django_q.tasks import async_task

from . import gemini_service
from .gemini_service import MerchantProductInfo
from groceries.models import SEARCH_DEFAULT_EMOJI, Search, SearchStatus
from groceries.schemas import SearchResultCandidateSchema
from groceries.url_page_context import fetch_page_text_for_product_context, is_http_https_url

from .merchants import preferred_merchant_context_for_user
from .products import CatalogInCatalogCheck

logger = logging.getLogger(__name__)


def _search_candidate_dict(p: MerchantProductInfo) -> dict[str, Any]:
    """JSON-serializable dict for ``Search.result_candidates``."""
    price_out: str | None = None
    if p.price is not None:
        price_out = str(p.price.quantize(Decimal("0.01")))
    return {
        "display_name": p.display_name,
        "standard_name": p.standard_name,
        "brand": p.brand,
        "price": price_out,
        "format": p.format,
        "emoji": p.emoji,
        "merchant": p.merchant,
        "ingredient": p.ingredient,
    }


def _search_candidates_as_json(items: list[MerchantProductInfo]) -> list[dict[str, Any]]:
    return [_search_candidate_dict(p) for p in items]


def _search_emoji_from_first_result_candidate(rows: list[dict[str, Any]]) -> str:
    """Persisted ``Search.emoji`` follows first row's ``emoji``; blank → magnifying glass default."""
    if rows and isinstance(rows[0], dict):
        raw = rows[0].get("emoji")
        if (s := str(raw or "").strip()):
            return s
    return SEARCH_DEFAULT_EMOJI


def create_search(*, query: str, user_id: int) -> int:
    """Create pending ``Search`` and enqueue Gemini worker; returns primary key."""
    normalized = query.strip()
    if not normalized:
        msg = "Query must not be empty."
        raise ValueError(msg)
    row = Search.objects.create(user_id=user_id, query=normalized)
    async_task(
        "groceries.scheduled_tasks.run_product_search_job",
        row.pk,
        task_name=f"groceries_product_search:{row.pk}",
    )
    return row.pk


def list_searches(*, user_id: int) -> list[Search]:
    """Latest 10 ``Search`` rows for *user_id*, newest first."""
    return list(
        Search.objects.filter(user_id=user_id).order_by("-created_at", "-pk")[:10],
    )


def get_search(search_id: int, *, user_id: int) -> Search:
    """Return one ``Search`` row owned by *user_id*."""
    return Search.objects.get(pk=search_id, user_id=user_id)


def delete_search(*, search_id: int, user_id: int) -> None:
    """Soft-delete ``Search`` row owned by *user_id*."""
    row = Search.objects.get(pk=search_id, user_id=user_id)
    now = timezone.now()
    row.deleted_at = now
    row.save(update_fields=["deleted_at"])


def retry_empty_completed_search(*, search_id: int, user_id: int) -> None:
    """Re-queue Gemini worker for *completed* row with empty ``result_candidates``."""
    row = Search.objects.get(pk=search_id, user_id=user_id)
    if row.status != SearchStatus.COMPLETED:
        msg = "Search is not completed; only completed empty-result searches can be retried."
        raise ValueError(msg)
    if row.result_candidates:
        msg = "Search already has result candidates; retry is not allowed."
        raise ValueError(msg)
    row.status = SearchStatus.PENDING
    row.completed_at = None
    row.save(update_fields=["status", "completed_at"])
    async_task(
        "groceries.scheduled_tasks.run_product_search_job",
        row.pk,
        task_name=f"groceries_product_search:{row.pk}",
    )


def search_result_candidates_as_product_schemas(
    raw: list[Any],
    *,
    fallback_name: str,
    in_catalog_check: CatalogInCatalogCheck | None = None,
) -> list[SearchResultCandidateSchema]:
    """Map persisted ``Search.result_candidates`` JSON to rows (optional *in_catalog_check* per candidate)."""
    q = (fallback_name or "").strip()
    out: list[SearchResultCandidateSchema] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        d: dict[str, Any] = item
        disp = str(d.get("display_name") or d.get("name") or "").strip()
        label = disp if disp else q
        std = str(d.get("standard_name") or "").strip()
        brand = str(d.get("brand") or "").strip()
        fmt = str(d.get("format") or "").strip()
        emoji = str(d.get("emoji") or "").strip()
        merchant = str(d.get("merchant") or "").strip()
        ing = str(d.get("ingredient") or "").strip()
        price_out: Decimal | None = None
        pr = d.get("price")
        if pr is not None and pr != "":
            try:
                price_out = Decimal(str(pr))
            except (ArithmeticError, ValueError, TypeError):
                price_out = None
        in_cat = (
            bool(in_catalog_check(label, std, brand))
            if in_catalog_check is not None
            else False
        )
        out.append(
            SearchResultCandidateSchema(
                name=label,
                standard_name=std,
                brand=brand,
                price=price_out,
                format=fmt,
                emoji=emoji,
                merchant=merchant,
                ingredient=ing,
                in_catalog=in_cat,
            ),
        )
    return out


def run_product_search_job(*, search_id: int) -> None:
    """Background worker: Gemini product candidates → ``Search`` row."""
    try:
        search = Search.all_objects.get(pk=search_id)
    except Search.DoesNotExist:
        logger.warning("run_product_search_job: missing Search id=%s", search_id)
        return
    if search.deleted_at is not None:
        logger.warning(
            "run_product_search_job: Search id=%s soft-deleted; skipping.",
            search_id,
        )
        return
    user_id = search.user_id
    q = search.query.strip()
    page_context: str | None = None
    if is_http_https_url(q):
        page_context = fetch_page_text_for_product_context(q)
    preferred = preferred_merchant_context_for_user(user_id)
    try:
        items = gemini_service.fetch_merchant_product_candidates(
            query=q,
            preferred_merchants=preferred,
            page_context=page_context,
        )
        candidates_json = _search_candidates_as_json(items)
        search.result_candidates = candidates_json
        search.emoji = _search_emoji_from_first_result_candidate(candidates_json)
        search.status = SearchStatus.COMPLETED
        search.completed_at = timezone.now()
        search.save(
            update_fields=[
                "result_candidates",
                "status",
                "completed_at",
                "emoji",
            ],
        )
    except RuntimeError:
        logger.warning(
            "run_product_search_job: GEMINI_API_KEY unset (search id=%s).",
            search_id,
        )
        search.status = SearchStatus.FAILED
        search.completed_at = timezone.now()
        search.save(update_fields=["status", "completed_at"])
    except Exception:
        logger.exception("run_product_search_job failed (search id=%s)", search_id)
        search.status = SearchStatus.FAILED
        search.completed_at = timezone.now()
        search.save(update_fields=["status", "completed_at"])
