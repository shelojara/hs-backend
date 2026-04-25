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

logger = logging.getLogger(__name__)

FIND_PRODUCTS_MAX = 10
# Full recipe (ingredients + steps) from title/notes.
RECIPE_FULL_INGREDIENTS_MAX = 25
RECIPE_FULL_STEPS_MAX = 35

# All Gemini calls use gemini-2.5-flash.
GEMINI_FIND_PRODUCTS_MODEL = "gemini-2.5-flash"

PRODUCT_EMOJI_SYSTEM_INSTRUCTION = (
    "You pick one Unicode emoji that best represents a grocery product for a shopping list. "
    "Reply with exactly one emoji and no other text."
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


RECIPE_FULL_CHILE_JSON_SYSTEM_INSTRUCTION = (
    "You help a home cook in Chile. Given a dish name and optional cook notes, output a complete recipe "
    "using ingredients and preparations typical in Chile (Lider/Jumbo style supermarkets; Spanish Chile; "
    "common Chilean products: e.g. aceite maravilla, merkén, choclo, pebre-style ideas when relevant, "
    "crema para cocinar, harina con polvos, etc.). "
    "Use Google Search when helpful to ground ingredient lists, amounts, and steps in credible references "
    "(especially for specific, regional, or ambiguous dish names or user constraints). "
    "Prefer Chilean dishes when the name fits; otherwise "
    "adapt the dish to Chile-available ingredients.\n"
    "Respond with a single JSON object only — no markdown, no code fences, no other text.\n"
    "Required keys:\n"
    f'- "ingredients": JSON array of at most {RECIPE_FULL_INGREDIENTS_MAX} objects. Each object has '
    '"name" (string: ingredient in Spanish Chile, short shelf-style phrase) and '
    '"amount" (string: quantity with unit, e.g. 500 g, 2 tazas, 1 cucharada; empty string if vague).\n'
    f'- "steps": JSON array of at most {RECIPE_FULL_STEPS_MAX} strings — ordered cooking steps in Spanish '
    "Chile, imperative or infinitive, one clear action per string.\n"
    "No duplicate ingredient names. Order ingredients from main to supporting. Steps must be practical "
    "and safe (cooking times, heat)."
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
class RecipeIngredientLine:
    name: str
    amount: str


@dataclass(frozen=True)
class RecipeFullFromGemini:
    ingredients: tuple[RecipeIngredientLine, ...]
    steps: tuple[str, ...]


RECIPE_CHAT_ANSWER_MAX_CHARS = 800
# Patch-style edits: smaller JSON than echoing full ingredients+steps.
RECIPE_OPS_MAX = 30

RECIPE_CHAT_JSON_SYSTEM_INSTRUCTION = (
    "You help a home cook in Chile chat about their saved recipe (title, notes, ingredients, steps). "
    "They may ask a short question, request substitutions, scaling, timing tips, or edits to ingredients/steps.\n"
    "The current recipe text uses zero-based indices: each line starts with ing[N] for ingredients "
    "and step[M] for steps. Use those N and M values in edits.\n"
    "The app never changes the saved recipe title or notes from your reply — only ingredients and steps "
    "can change when updating.\n"
    "Respond with a single JSON object only — no markdown, no code fences, no other text.\n"
    "Required keys:\n"
    f'- "answer" (string: concise reply in Spanish Chile when the recipe is in Spanish; '
    f"at most {RECIPE_CHAT_ANSWER_MAX_CHARS} characters; practical and safe for cooking).\n"
    '- "update_recipe" (boolean): true only if the user asked to change the stored recipe '
    "(ingredients and/or steps) and you can describe the edits; "
    "false for pure Q&A, tips, or when you should not change ingredients/steps.\n"
    '- When "update_recipe" is true, prefer a compact "recipe_ops" array (at most '
    f"{RECIPE_OPS_MAX} objects) instead of resending the full recipe. Apply ops in order; each op "
    "sees the list state after previous ops. Valid op shapes (field \"op\" is required):\n"
    '  - {"op": "replace_ingredient", "index": <int>, "name": <string>, "amount": <string optional>}\n'
    '  - {"op": "remove_ingredient", "index": <int>}\n'
    '  - {"op": "insert_ingredient", "index": <int>, "name": <string>, "amount": <string optional>} '
    "— insert before current ingredient at index; index may equal current length to append.\n"
    '  - {"op": "replace_step", "index": <int>, "text": <string>}\n'
    '  - {"op": "remove_step", "index": <int>}\n'
    '  - {"op": "insert_step", "index": <int>, "text": <string>} '
    "— insert before current step at index; index may equal current length to append.\n"
    "After all ops, the recipe must still have at least one ingredient and one step, unique ingredient "
    "names (case-insensitive), and respect caps: at most "
    f"{RECIPE_FULL_INGREDIENTS_MAX} ingredients and {RECIPE_FULL_STEPS_MAX} steps.\n"
    'Legacy alternative when rewriting almost everything: omit "recipe_ops" and instead send full '
    f'"ingredients" (array of {{name, amount}}) and "steps" (array of strings) as before — same limits '
    "and non-empty when used.\n"
    'When "update_recipe" is false, omit "recipe_ops", "ingredients", and "steps" (or use empty arrays) '
    "— prefer omitting.\n"
    'If "update_recipe" is true with "recipe_ops", omit full "ingredients" and "steps" when possible.'
)


@dataclass(frozen=True)
class RecipeChatFromGemini:
    """Model output: short reply plus optional patch ops or full ingredients+steps replacement."""

    answer: str
    update_recipe: bool
    updated: RecipeFullFromGemini | None
    recipe_ops: tuple[dict[str, Any], ...] | None = None
    gemini_response_raw: str = ""


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


def suggest_product_emoji(
    *,
    name: str,
    standard_name: str = "",
    brand: str = "",
    format: str = "",
) -> str:
    """Ask Gemini for one emoji for *name* plus optional catalog fields."""
    lines = [f"Product name: {name.strip()!r}"]
    sn = (standard_name or "").strip()
    if sn:
        lines.append(f"Generic type (standard name): {sn!r}")
    br = (brand or "").strip()
    if br:
        lines.append(f"Brand: {br!r}")
    fmt = (format or "").strip()
    if fmt:
        lines.append(f"Format / size: {fmt!r}")
    lines.append("\nSuggest one emoji for this product.")
    prompt = "\n".join(lines)

    client = _get_client()
    response = client.models.generate_content(
        model=GEMINI_FIND_PRODUCTS_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=PRODUCT_EMOJI_SYSTEM_INSTRUCTION,
            temperature=0.35,
        ),
    )
    text = (response.text or "").strip().strip("\"'")
    if not text:
        logger.warning("Gemini returned empty emoji for product %r", name)
        return "📦"
    return _normalize_field(text, 64)


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


def _parse_recipe_full_chile_payload(
    raw: str | None,
    *,
    max_ingredients: int,
    max_steps: int,
) -> RecipeFullFromGemini | None:
    """Parse ``ingredients`` + ``steps`` object from model output; ``None`` if unusable."""
    if not raw or max_ingredients < 1 or max_steps < 1:
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
    ing_raw = data.get("ingredients")
    if not isinstance(ing_raw, list):
        return None
    lines: list[RecipeIngredientLine] = []
    seen_names: set[str] = set()
    for item in ing_raw:
        if len(lines) >= max_ingredients:
            break
        name = ""
        amount = ""
        if isinstance(item, str):
            name = item.strip()
        elif isinstance(item, dict):
            name = _normalize_field(
                item.get("name") or item.get("ingredient") or item.get("item"),
                255,
            )
            amount = _normalize_field(
                item.get("amount")
                or item.get("quantity")
                or item.get("cantidad")
                or item.get("q"),
                255,
            )
        if not name:
            continue
        key = name.casefold()
        if key in seen_names:
            continue
        seen_names.add(key)
        lines.append(RecipeIngredientLine(name=name, amount=amount))

    steps_raw = data.get("steps")
    if not isinstance(steps_raw, list):
        return None
    steps_out: list[str] = []
    for s in steps_raw:
        if len(steps_out) >= max_steps:
            break
        if isinstance(s, str):
            t = " ".join(s.split()).strip()
            if t:
                steps_out.append(_clip(t, 4000))
        elif isinstance(s, dict):
            t = _normalize_field(
                s.get("text") or s.get("step") or s.get("instruction"),
                4000,
            )
            if t:
                steps_out.append(t)
    if not lines or not steps_out:
        return None
    return RecipeFullFromGemini(
        ingredients=tuple(lines),
        steps=tuple(steps_out),
    )


def _coerce_non_negative_int(raw: Any) -> int | None:
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int) and raw >= 0:
        return raw
    if isinstance(raw, float) and raw.is_integer():
        n = int(raw)
        return n if n >= 0 else None
    return None


def apply_recipe_patch_ops(
    *,
    ingredients: list[tuple[str, str]],
    steps: list[str],
    ops: Sequence[dict[str, Any]],
    max_ingredients: int,
    max_steps: int,
) -> RecipeFullFromGemini | None:
    """Apply ordered patch ops to ingredient/step lists; return full recipe or None if invalid."""
    if max_ingredients < 1 or max_steps < 1:
        return None
    ing: list[tuple[str, str]] = [
        (_normalize_field(n, 255), _normalize_field(a, 255)) for n, a in ingredients
    ]
    st: list[str] = []
    for t in steps:
        u = _clip(_normalize_field(t, 4000), 4000)
        if u:
            st.append(u)
    if not ing or not st:
        return None

    def ingredient_names_unique() -> bool:
        seen: set[str] = set()
        for n, _a in ing:
            k = n.casefold()
            if k in seen:
                return False
            seen.add(k)
        return True

    for raw_op in ops:
        if not isinstance(raw_op, dict):
            return None
        kind = str(raw_op.get("op") or "").strip().lower()
        if kind == "replace_ingredient":
            idx = _coerce_non_negative_int(raw_op.get("index"))
            if idx is None or idx >= len(ing):
                return None
            name = _normalize_field(raw_op.get("name"), 255)
            if not name:
                return None
            amount = _normalize_field(raw_op.get("amount"), 255)
            ing[idx] = (name, amount)
            if not ingredient_names_unique():
                return None
        elif kind == "remove_ingredient":
            idx = _coerce_non_negative_int(raw_op.get("index"))
            if idx is None or idx >= len(ing):
                return None
            del ing[idx]
            if len(ing) < 1:
                return None
        elif kind == "insert_ingredient":
            idx = _coerce_non_negative_int(raw_op.get("index"))
            if idx is None or idx > len(ing):
                return None
            if len(ing) >= max_ingredients:
                return None
            name = _normalize_field(raw_op.get("name"), 255)
            if not name:
                return None
            amount = _normalize_field(raw_op.get("amount"), 255)
            ing.insert(idx, (name, amount))
            if not ingredient_names_unique():
                return None
        elif kind == "replace_step":
            idx = _coerce_non_negative_int(raw_op.get("index"))
            if idx is None or idx >= len(st):
                return None
            text = _normalize_field(raw_op.get("text"), 4000)
            if not text:
                return None
            st[idx] = text
        elif kind == "remove_step":
            idx = _coerce_non_negative_int(raw_op.get("index"))
            if idx is None or idx >= len(st):
                return None
            del st[idx]
            if len(st) < 1:
                return None
        elif kind == "insert_step":
            idx = _coerce_non_negative_int(raw_op.get("index"))
            if idx is None or idx > len(st):
                return None
            if len(st) >= max_steps:
                return None
            text = _normalize_field(raw_op.get("text"), 4000)
            if not text:
                return None
            st.insert(idx, text)
        else:
            return None

        if len(ing) > max_ingredients or len(st) > max_steps:
            return None

    if not ing or not st or not ingredient_names_unique():
        return None
    return RecipeFullFromGemini(
        ingredients=tuple(RecipeIngredientLine(name=n, amount=a) for n, a in ing),
        steps=tuple(st),
    )


def _parse_recipe_chat_payload(
    raw: str | None,
    *,
    max_ingredients: int,
    max_steps: int,
) -> RecipeChatFromGemini | None:
    if not raw or max_ingredients < 1 or max_steps < 1:
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
    answer = _normalize_field(data.get("answer"), RECIPE_CHAT_ANSWER_MAX_CHARS)
    if not answer:
        return None
    want_update = data.get("update_recipe")
    if isinstance(want_update, str):
        want_update = want_update.strip().lower() in {"1", "true", "yes", "sí", "si"}
    update_recipe = bool(want_update)
    if not update_recipe:
        return RecipeChatFromGemini(
            answer=answer,
            update_recipe=False,
            updated=None,
            recipe_ops=None,
            gemini_response_raw=raw or "",
        )
    ops_raw = data.get("recipe_ops")
    ops_list: list[dict[str, Any]] = []
    if isinstance(ops_raw, list):
        for item in ops_raw:
            if len(ops_list) >= RECIPE_OPS_MAX:
                break
            if isinstance(item, dict):
                ops_list.append(dict(item))
    if ops_list:
        return RecipeChatFromGemini(
            answer=answer,
            update_recipe=True,
            updated=None,
            recipe_ops=tuple(ops_list),
            gemini_response_raw=raw or "",
        )
    inner = json.dumps(
        {
            "ingredients": data.get("ingredients"),
            "steps": data.get("steps"),
        },
        ensure_ascii=False,
    )
    full = _parse_recipe_full_chile_payload(
        inner,
        max_ingredients=max_ingredients,
        max_steps=max_steps,
    )
    if full is None:
        return None
    return RecipeChatFromGemini(
        answer=answer,
        update_recipe=True,
        updated=full,
        recipe_ops=None,
        gemini_response_raw=raw or "",
    )


def fetch_recipe_full_chile(
    *,
    title: str,
    notes: str = "",
    max_ingredients: int = RECIPE_FULL_INGREDIENTS_MAX,
    max_steps: int = RECIPE_FULL_STEPS_MAX,
) -> RecipeFullFromGemini | None:
    """Ask Gemini for full recipe (ingredient names + amounts + steps) for Chile home kitchen."""
    name = (title or "").strip()
    if not name:
        return None
    n_ing = max(1, min(max_ingredients, RECIPE_FULL_INGREDIENTS_MAX))
    n_st = max(1, min(max_steps, RECIPE_FULL_STEPS_MAX))
    note_block = (notes or "").strip()
    prompt_parts = [f"Dish name: {name!r}"]
    if note_block:
        prompt_parts.append(f"Cook notes / constraints from user:\n{note_block}")
    prompt_parts.append(
        f"Return the JSON object with ingredients (max {n_ing}) and steps (max {n_st}) "
        "as described in the system instruction.",
    )
    prompt = "\n\n".join(prompt_parts)

    client = _get_client()
    grounding = types.Tool(google_search=types.GoogleSearch())
    response = client.models.generate_content(
        model=GEMINI_FIND_PRODUCTS_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=RECIPE_FULL_CHILE_JSON_SYSTEM_INSTRUCTION,
            temperature=0.3,
            tools=[grounding],
        ),
    )
    return _parse_recipe_full_chile_payload(
        response.text,
        max_ingredients=n_ing,
        max_steps=n_st,
    )


RECIPE_CHAT_USER_MESSAGE_MAX = 4000
RECIPE_CHAT_CONTEXT_MAX = 12000


def fetch_recipe_chat_chile(
    *,
    recipe_context: str,
    user_message: str,
    max_ingredients: int = RECIPE_FULL_INGREDIENTS_MAX,
    max_steps: int = RECIPE_FULL_STEPS_MAX,
) -> RecipeChatFromGemini | None:
    """Ask Gemini for a short answer and optionally a full recipe update JSON."""
    msg = (user_message or "").strip()
    if not msg:
        return None
    msg = _clip(msg, RECIPE_CHAT_USER_MESSAGE_MAX)
    ctx = (recipe_context or "").strip()
    if not ctx:
        return None
    ctx = _clip(ctx, RECIPE_CHAT_CONTEXT_MAX)
    n_ing = max(1, min(max_ingredients, RECIPE_FULL_INGREDIENTS_MAX))
    n_st = max(1, min(max_steps, RECIPE_FULL_STEPS_MAX))
    prompt = (
        "Current recipe (title and notes are fixed in the database; only ingredients and steps may be "
        "replaced when update_recipe is true):\n"
        f"{ctx}\n\n"
        f"User message:\n{msg}\n\n"
        f"When update_recipe is true, cap ingredients at {n_ing} and steps at {n_st}. "
        "Return the JSON object described in the system instruction."
    )
    client = _get_client()
    response = client.models.generate_content(
        model=GEMINI_FIND_PRODUCTS_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=RECIPE_CHAT_JSON_SYSTEM_INSTRUCTION,
            temperature=0.35,
        ),
    )
    return _parse_recipe_chat_payload(
        response.text,
        max_ingredients=n_ing,
        max_steps=n_st,
    )


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
