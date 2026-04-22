import json
import logging
import os
import re
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from google import genai
from google.genai import types

from groceries.models import SearchQueryKind

logger = logging.getLogger(__name__)

FIND_PRODUCTS_MAX = 10
# Recipe flow: one merchant row per ingredient line (cap total array size).
RECIPE_INGREDIENT_FINDS_MAX = 20

# All Gemini calls use gemini-2.5-flash.
GEMINI_FIND_PRODUCTS_MODEL = "gemini-2.5-flash"

_SEARCH_QUERY_KIND_OK = frozenset({c.value for c in SearchQueryKind})

SEARCH_QUERY_KIND_SYSTEM_INSTRUCTION = (
    "You classify a grocery-app search box string from a shopper. "
    "Decide the primary intent:\n"
    '- "product" — looking for a type of product to buy (e.g. "oat milk", "rice 1kg", "pasta").\n'
    '- "brand" — mainly a brand or manufacturer name (e.g. "Colún", "Nestlé", "Lider brand X").\n'
    '- "recipe" — dish or meal to cook; ingredients implied (e.g. "carbonara", "chile con carne").\n'
    '- "question" — how-to, nutrition, comparison, or other non-catalog question.\n'
    "Respond with a single JSON object only — no markdown, no code fences, no other text. "
    'Exactly one key: "kind" whose value is one of: "product", "brand", "recipe", "question".'
)

RUNNING_LOW_MAX_SUGGESTIONS = 15

RUNNING_LOW_SYSTEM_INSTRUCTION = (
    "You help a household grocery shopper anywhere in the world. "
    "You receive purchase history: completed shopping baskets from roughly the last two months, newest first, "
    "each with purchase timestamp and product lines. Each line starts with "
    '"[product_id=N]" where N is that row’s database id — use these ids to tie suggestions to products. '
    "Infer which items the shopper is likely running low on soon, based on: "
    "typical consumption rates for those product types, time since last purchase in each basket, "
    "and whether staples appear less often than expected. "
    "This is a rough heuristic — be practical and concise. "
    "Respond with a single JSON array only — no markdown, no code fences, no text before or after. "
    f"At most {RUNNING_LOW_MAX_SUGGESTIONS} elements. Each element is one JSON object with keys: "
    '"product_name" (string: short label in the same language as the product lines when possible), '
    '"reason" (string: one short sentence why it may run out soon), '
    '"urgency" (string: one of \"high\", \"medium\", \"low\"), '
    '"product_ids" (JSON array of integers: which [product_id=...] values from the history apply; '
    "omit or use [] only when unsure). "
    "If there is not enough history to infer anything useful, return []. "
    "Do not invent product_ids that never appear in the history."
)


_MERCHANT_PRODUCT_JSON_KEYS_FIND = (
    "Each object must have these keys: "
    '"merchant" (string: retail chain or store name whose Chile site or listing you used, e.g. "Lider", "Jumbo"; '
    "Spanish Chile when appropriate; empty if unknown), "
    '"display_name" (string: best retail-style product title for lists: proper capitalization, '
    "brand + product line + key format as on shelf or the merchant site; Spanish Chile; empty if unknown), "
    '"standard_name" (string: generic product type for grouping across brands and formats: Spanish Chile; '
    'omit marca, precio, and envase/tamaño; short noun phrase e.g. "Leche entera", "Arroz grano largo"; '
    "empty if unknown), "
    '"brand" (string: marca comercial or empty), '
    '"price" (number or null: typical shelf price in Chilean pesos CLP as a plain number — integer pesos, '
    "no thousands separators, no currency symbol; e.g. 3990 for a shelf label like $3.990; use null if unknown), "
    '"format" (string: presentation: size, units, e.g. "1 L", "6 x 330 ml", "500 g"; empty if unknown), '
    '"emoji" (string: one Unicode emoji best matching product type or category, e.g. 🥛 for milk, 🍚 for rice; '
    'empty string "" if unsure). '
    'Use empty string "" for unknown string fields. Use JSON null for unknown price (legacy 0 is treated as unknown). '
    "Do not repeat the same merchant SKU or identical display_name twice. Prefer distinct products."
)

_RECIPE_INGREDIENT_PRODUCT_JSON_KEYS = (
    "Each object must have these keys: "
    '"ingredient" (string: one recipe ingredient the product row satisfies — short Spanish Chile phrase, '
    "e.g. \"Pasta\", \"Crema para cocinar\"; empty if unknown), "
    '"display_name" (string: best retail-style product title for lists: proper capitalization, '
    "brand + product line + key format as commonly sold in the shopper's locality; Spanish Chile when locality is Chile; "
    "empty if unknown), "
    '"standard_name" (string: generic product type for grouping across brands and formats: Spanish Chile; '
    'omit marca, precio, and envase/tamaño; short noun phrase e.g. "Leche entera", "Arroz grano largo"; '
    "empty if unknown), "
    '"brand" (string: marca comercial or empty), '
    '"price" (number or null: typical shelf price in Chilean pesos CLP as a plain number — integer pesos, '
    "no thousands separators, no currency symbol; e.g. 3990 for a shelf label like $3.990; use null if unknown), "
    '"format" (string: presentation: size, units, e.g. "1 L", "6 x 330 ml", "500 g"; empty if unknown), '
    '"emoji" (string: one Unicode emoji best matching product type or category, e.g. 🥛 for milk, 🍚 for rice; '
    'empty string "" if unsure). '
    'Use empty string "" for unknown string fields. Use JSON null for unknown price (legacy 0 is treated as unknown). '
    "Include at most one primary product row per distinct ingredient line. "
    "Do not repeat identical display_name twice."
)

_MERCHANT_PRODUCT_JSON_KEYS_SINGLE = (
    'Keys: "display_name" (string: best retail-style product title for lists: proper capitalization, '
    "brand + product line + key format as on shelf or the merchant site; Spanish Chile; empty if unknown), "
    '"standard_name" (string: generic product type for grouping across brands and formats: Spanish Chile; '
    'omit marca, precio, and envase/tamaño; short noun phrase e.g. "Leche entera", "Arroz grano largo"; '
    "empty if unknown), "
    '"brand" (string: marca comercial or empty), '
    '"price" (number or null: typical shelf price in Chilean pesos CLP as a plain number — integer pesos, '
    "no thousands separators, no currency symbol; e.g. 3990 for a shelf label like $3.990; use null if unknown), "
    '"format" (string: presentation: size, units, e.g. "1 L", "6 x 330 ml", "500 g"; empty if unknown), '
    '"emoji" (string: one Unicode emoji best matching product type or category, e.g. 🥛 for milk, 🍚 for rice; '
    'empty string "" if unsure). '
    'Use empty string "" for unknown string fields. Use JSON null for unknown price (legacy 0 is treated as unknown).'
)


@dataclass(frozen=True)
class PreferredMerchantContext:
    """User-preferred store (name + site) for Gemini Chile grocery search."""

    name: str
    website: str


def _merchant_scope_paragraph(
    *,
    preferred: Sequence[PreferredMerchantContext] | None,
    multi_query: bool,
) -> str:
    """Intro paragraph: default Lider or user's preferred merchant list."""
    if not preferred:
        return (
            "You help catalog grocery products sold in Chile for a specific retail merchant "
            "(default: Lider / Walmart Chile, website líder.cl). "
            + (
                "Use Google Search to find how products matching the user's query appear on that merchant's site "
                "or in that merchant's Chile listings when possible. "
                if multi_query
                else "Use Google Search to find how this product appears on that merchant's site or in that merchant's "
                "Chile listings when possible. "
            )
        )
    lines = [
        "You help catalog grocery products sold in Chile for the shopper's preferred retail merchant(s).",
        "Preferred merchants (earlier = higher priority when choosing one site):",
    ]
    for i, m in enumerate(preferred, start=1):
        nm = (m.name or "").strip() or f"Merchant {i}"
        web = (m.website or "").strip()
        lines.append(f"{i}. {nm} — {web}" if web else f"{i}. {nm}")
    tail = (
        "Use Google Search to find listings on these site(s); prefer the first merchant when several apply. "
        + (
            "Match products matching the user's query."
            if multi_query
            else "Match this product."
        )
    )
    lines.append(tail)
    return "\n".join(lines)


def _recipe_locality_scope_paragraph() -> str:
    """Recipe ingredient flow: Chile default; no single-store-site prioritization."""
    return (
        "The shopper's grocery locality defaults to Chile unless the recipe query clearly names another country or region. "
        "Use Google Search to learn which grocery ingredients and typical shelf products for that dish are common in that "
        "locality (supermarkets, home cooking, regional names). "
        "Do not prioritize any specific retail chain or store website; ignore preferred-store lists. "
        "Ground answers in what is realistically bought for home cooking there."
    )


def merchant_product_find_system_instruction(
    *,
    preferred: Sequence[PreferredMerchantContext] | None = None,
) -> str:
    """System instruction for multi-product search JSON array."""
    head = _merchant_scope_paragraph(preferred=preferred, multi_query=True)
    return (
        f"{head}"
        f"Respond with a single JSON array only — no markdown, no code fences, no text before or after. "
        f"The array must have at most {FIND_PRODUCTS_MAX} elements. Each element is one JSON object with the "
        f"{_MERCHANT_PRODUCT_JSON_KEYS_FIND}"
    )


def recipe_ingredient_product_find_system_instruction(
    *,
    preferred: Sequence[PreferredMerchantContext] | None = None,
) -> str:
    """System instruction: recipe → JSON array of ingredient-labeled rows (locality-first; *preferred* ignored)."""
    _ = preferred
    head = _recipe_locality_scope_paragraph()
    return (
        f"{head}"
        "The user named a dish or recipe to cook — not a single product query. "
        "Infer typical grocery ingredients (proteins, produce, pantry, dairy, etc.) for that dish as a home cook in the "
        "shopper's locality would shop for them. "
        f"Respond with a single JSON array only — no markdown, no code fences, no text before or after. "
        f"The array must have at most {RECIPE_INGREDIENT_FINDS_MAX} elements. Each element is one JSON object with the "
        f"{_RECIPE_INGREDIENT_PRODUCT_JSON_KEYS}"
    )


def merchant_product_single_system_instruction(
    *,
    preferred: Sequence[PreferredMerchantContext] | None = None,
) -> str:
    """System instruction for single-product JSON object."""
    head = _merchant_scope_paragraph(preferred=preferred, multi_query=False)
    return (
        f"{head}"
        "Respond with a single JSON object only — no markdown, no code fences, no text before or after. "
        f"{_MERCHANT_PRODUCT_JSON_KEYS_SINGLE}"
    )


@dataclass(frozen=True)
class MerchantProductInfo:
    display_name: str
    standard_name: str
    brand: str
    price: Decimal | None
    format: str
    emoji: str
    merchant: str = ""
    ingredient: str = ""


@dataclass(frozen=True)
class RunningLowSuggestion:
    product_name: str
    reason: str
    urgency: str
    product_ids: tuple[int, ...] = ()


def _get_client() -> genai.Client:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        msg = (
            "GEMINI_API_KEY environment variable is not set. "
            "Please set it to a valid Gemini API key."
        )
        raise RuntimeError(msg)
    return genai.Client(api_key=api_key)


def _clip(s: str, max_len: int) -> str:
    if len(s) <= max_len:
        return s
    return s[: max_len - 3].rstrip() + "..."


def _normalize_field(s: str | None, max_len: int) -> str:
    if not s:
        return ""
    text = " ".join(str(s).split())
    return _clip(text, max_len) if text else ""


def _quantize_clp(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _parse_optional_merchant_price(raw: Any) -> Decimal | None:
    """Parse JSON price; ``None``, empty, invalid, unknown sentinel 0 → ``None``."""
    if raw is None:
        return None
    if isinstance(raw, str) and not raw.strip():
        return None
    parsed = _parse_price_value(raw)
    if parsed == Decimal("0"):
        return None
    return parsed


def _parse_price_value(raw: Any) -> Decimal:
    """Turn Gemini JSON price (number or legacy string like '$3.990') into Decimal CLP."""
    if raw is None:
        return Decimal("0")
    if isinstance(raw, bool):
        return Decimal("0")
    if isinstance(raw, int):
        return _quantize_clp(Decimal(raw))
    if isinstance(raw, float):
        return _quantize_clp(Decimal(str(raw)))
    if isinstance(raw, Decimal):
        return _quantize_clp(raw)
    s = str(raw).strip()
    if not s:
        return Decimal("0")
    cleaned = s.replace("$", "").replace("CLP", "").strip()
    cleaned = re.sub(r"\s+", "", cleaned)
    digits_only = re.sub(r"[^\d]", "", cleaned)
    if digits_only:
        try:
            return _quantize_clp(Decimal(digits_only))
        except InvalidOperation:
            pass
    try:
        return _quantize_clp(Decimal(cleaned.replace(",", ".")))
    except InvalidOperation:
        return Decimal("0")


_JSON_FENCE = re.compile(r"^\s*```(?:json)?\s*([\s\S]*?)\s*```\s*$", re.IGNORECASE)


def _extract_json_object(raw: str) -> str | None:
    """Strip optional markdown fence; return inner JSON object string or None."""
    if not raw:
        return None
    text = raw.strip()
    m = _JSON_FENCE.match(text)
    if m:
        text = m.group(1).strip()
    if text.startswith("{") and text.endswith("}"):
        return text
    # Try first {...} span
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        return text[start : end + 1]
    return None


def _merchant_product_info_from_mapping(data: dict[str, Any]) -> MerchantProductInfo:
    return MerchantProductInfo(
        display_name=_normalize_field(data.get("display_name"), 255),
        standard_name=_normalize_field(data.get("standard_name"), 255),
        brand=_normalize_field(data.get("brand"), 255),
        price=_parse_optional_merchant_price(data.get("price")),
        format=_normalize_field(data.get("format"), 255),
        emoji=_normalize_field(data.get("emoji"), 64),
        merchant=_normalize_field(data.get("merchant"), 255),
        ingredient=_normalize_field(data.get("ingredient"), 255),
    )


def _parse_merchant_product_payload(raw: str | None) -> MerchantProductInfo | None:
    """Parse model output into structured fields; require valid JSON object."""
    if not raw:
        return None
    blob = _extract_json_object(raw)
    if not blob:
        return None
    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return _merchant_product_info_from_mapping(data)


def _extract_json_array(raw: str) -> str | None:
    text = raw.strip()
    m = _JSON_FENCE.match(text)
    if m:
        text = m.group(1).strip()
    if text.startswith("[") and text.endswith("]"):
        return text
    start, end = text.find("["), text.rfind("]")
    if start != -1 and end > start:
        return text[start : end + 1]
    return None


def _parse_merchant_product_list_payload(
    raw: str | None,
    *,
    max_items: int,
) -> list[MerchantProductInfo]:
    """Parse model output into zero or more structured products; cap at *max_items*."""
    if not raw or max_items < 1:
        return []
    blob = _extract_json_array(raw)
    if not blob:
        single = _parse_merchant_product_payload(raw)
        return [single] if single else []
    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        single = _parse_merchant_product_payload(raw)
        return [single] if single else []
    if (
        isinstance(data, dict)
        and "products" in data
        and isinstance(data["products"], list)
    ):
        data = data["products"]
    elif isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        return []
    out: list[MerchantProductInfo] = []
    for item in data:
        if len(out) >= max_items:
            break
        if not isinstance(item, dict):
            continue
        out.append(_merchant_product_info_from_mapping(item))
    return out


def fetch_merchant_product_info_by_identity(
    *,
    standard_name: str,
    brand: str,
    format: str,
    preferred_merchants: Sequence[PreferredMerchantContext] | None = None,
) -> MerchantProductInfo | None:
    """Ask Gemini (with Google Search) for Chile merchant-structured product info by catalog identity."""
    sn = (standard_name or "").strip()
    if not sn:
        return None
    br = (brand or "").strip()
    fmt = (format or "").strip()

    prompt = (
        "Product identity (grouping fields — find this SKU or closest shelf match):\n"
        f"- standard_name: {sn!r}\n"
        f"- brand: {br!r}\n"
        f"- format: {fmt!r}\n\n"
        "Search the merchant's Chile site for this product (match type, brand, and pack size when possible) "
        "and fill the JSON with the current listing."
    )

    client = _get_client()
    grounding = types.Tool(google_search=types.GoogleSearch())
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=merchant_product_single_system_instruction(
                preferred=preferred_merchants,
            ),
            temperature=0.25,
            tools=[grounding],
        ),
    )
    return _parse_merchant_product_payload(response.text)


def fetch_merchant_product_candidates(
    *,
    query: str,
    max_products: int = FIND_PRODUCTS_MAX,
    preferred_merchants: Sequence[PreferredMerchantContext] | None = None,
    page_context: str | None = None,
) -> list[MerchantProductInfo]:
    """Ask Gemini for up to *max_products* distinct merchant product rows for *query*."""
    name = (query or "").strip()
    if not name:
        return []
    lim = max(1, min(max_products, FIND_PRODUCTS_MAX))

    ctx = (page_context or "").strip()
    if ctx:
        prompt = (
            f"The user pasted a product or listing page URL (reference only): {name!r}\n\n"
            "Below is plain text extracted from that page (may be noisy). "
            "Infer product identity (name, brand, format, price if visible) from this content.\n\n"
            f"--- page text ---\n{ctx}\n--- end ---\n\n"
            f"Return up to {lim} distinct products implied by this page as the JSON array described in the "
            "system instruction. Prefer the main product on the page when it is a single-product listing; "
            "otherwise include distinct items found in the content."
        )
    else:
        prompt = (
            f"Product search query (as entered by user): {name!r}\n\n"
            f"Search the merchant's Chile site and return up to {lim} distinct matching products as the "
            "JSON array described in the system instruction."
        )

    client = _get_client()
    grounding = types.Tool(google_search=types.GoogleSearch())
    response = client.models.generate_content(
        model=GEMINI_FIND_PRODUCTS_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=merchant_product_find_system_instruction(
                preferred=preferred_merchants,
            ),
            temperature=0.25,
            tools=[grounding],
        ),
    )
    return _parse_merchant_product_list_payload(response.text, max_items=lim)


def fetch_recipe_ingredient_product_candidates(
    *,
    recipe_query: str,
    max_products: int = RECIPE_INGREDIENT_FINDS_MAX,
    preferred_merchants: Sequence[PreferredMerchantContext] | None = None,
) -> list[MerchantProductInfo]:
    """Ask Gemini for product rows keyed by inferred recipe ingredients (locality-first; *preferred_merchants* ignored)."""
    _ = preferred_merchants
    name = (recipe_query or "").strip()
    if not name:
        return []
    lim = max(1, min(max_products, RECIPE_INGREDIENT_FINDS_MAX))

    prompt = (
        f"Recipe or dish the shopper wants to cook (as entered): {name!r}\n\n"
        "Shopper locality defaults to Chile unless the query clearly indicates another place. "
        "Use Google Search for how this dish is typically made and shopped for in that locality — ingredients, "
        "common product types, and Spanish Chile names when locality is Chile. "
        "Do not anchor on specific supermarket chains or retailer sites. "
        f"For each important grocery ingredient, return one representative purchasable product as the JSON array "
        f"described in the system instruction. Return at most {lim} elements total."
    )

    client = _get_client()
    grounding = types.Tool(google_search=types.GoogleSearch())
    response = client.models.generate_content(
        model=GEMINI_FIND_PRODUCTS_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=recipe_ingredient_product_find_system_instruction(
                preferred=preferred_merchants,
            ),
            temperature=0.25,
            tools=[grounding],
        ),
    )
    return _parse_merchant_product_list_payload(response.text, max_items=lim)


def _parse_search_query_kind_payload(raw: str | None) -> str:
    """Return validated ``SearchQueryKind`` value or empty string."""
    if not raw:
        return ""
    blob = _extract_json_object(raw)
    if not blob:
        return ""
    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        return ""
    if not isinstance(data, dict):
        return ""
    val = str(data.get("kind") or "").strip().lower()
    return val if val in _SEARCH_QUERY_KIND_OK else ""


def classify_search_query_kind(*, query: str) -> str:
    """Ask Gemini for ``SearchQueryKind`` label; empty string if unparseable or blank *query*."""
    q = (query or "").strip()
    if not q:
        return ""

    prompt = f"Classify this search query:\n{q!r}"

    try:
        client = _get_client()
    except RuntimeError:
        raise
    except Exception:
        logger.exception("classify_search_query_kind: client init failed")
        return ""

    try:
        response = client.models.generate_content(
            model=GEMINI_FIND_PRODUCTS_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=SEARCH_QUERY_KIND_SYSTEM_INSTRUCTION,
                temperature=0.1,
            ),
        )
    except Exception:
        logger.exception("classify_search_query_kind: generate_content failed")
        return ""

    return _parse_search_query_kind_payload(response.text)


_URGENCY_OK = frozenset({"high", "medium", "low"})
_LEGACY_URGENCY = {"alta": "high", "media": "medium", "baja": "low"}


def _parse_running_low_suggestions(
    raw: str | None,
    *,
    max_items: int,
) -> list[RunningLowSuggestion]:
    """Parse model JSON array into structured suggestions; cap at *max_items*."""
    if not raw or max_items < 1:
        return []
    blob = _extract_json_array(raw)
    if not blob:
        return []
    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        return []
    if (
        isinstance(data, dict)
        and "suggestions" in data
        and isinstance(data["suggestions"], list)
    ):
        data = data["suggestions"]
    elif isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        return []
    out: list[RunningLowSuggestion] = []
    for item in data:
        if len(out) >= max_items:
            break
        if not isinstance(item, dict):
            continue
        name = _normalize_field(item.get("product_name"), 255)
        reason = _normalize_field(item.get("reason"), 512)
        if not name or not reason:
            continue
        u_raw = str(item.get("urgency") or "").strip().lower()
        if u_raw in _LEGACY_URGENCY:
            urgency = _LEGACY_URGENCY[u_raw]
        elif u_raw in _URGENCY_OK:
            urgency = u_raw
        else:
            urgency = "medium"
        pid_raw = item.get("product_ids")
        pids: list[int] = []
        if isinstance(pid_raw, list):
            for x in pid_raw:
                if isinstance(x, bool):
                    continue
                if isinstance(x, int):
                    pids.append(x)
                elif isinstance(x, float) and float(x).is_integer():
                    pids.append(int(x))
        out.append(
            RunningLowSuggestion(
                product_name=name,
                reason=reason,
                urgency=urgency,
                product_ids=tuple(pids),
            ),
        )
    return out


def suggest_running_low_from_purchase_history(
    *,
    history_markdown: str,
    max_suggestions: int = RUNNING_LOW_MAX_SUGGESTIONS,
) -> list[RunningLowSuggestion]:
    """Ask Gemini which products from *history_markdown* may run out soon.

    *history_markdown* should describe up to 5 newest purchased baskets (timestamps + lines).
    Returns empty list when *history_markdown* is blank.
    """
    text = (history_markdown or "").strip()
    if not text:
        return []
    lim = max(1, min(max_suggestions, RUNNING_LOW_MAX_SUGGESTIONS))

    prompt = (
        "Below is the shopper's recent completed basket history (newest baskets first). "
        "Suggest which products they may run low on soon.\n\n"
        f"{text}"
    )

    client = _get_client()
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=RUNNING_LOW_SYSTEM_INSTRUCTION,
            temperature=0.35,
        ),
    )
    return _parse_running_low_suggestions(response.text, max_items=lim)
