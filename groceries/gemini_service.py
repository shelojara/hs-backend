import json
import logging
import os
import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

FIND_PRODUCTS_MAX = 10

LIDER_PRODUCT_FIND_SYSTEM_INSTRUCTION = (
    "You help catalog grocery products sold in Chile at Lider (Walmart Chile), website líder.cl. "
    "Use Google Search to find how products matching the user's query appear on líder.cl or in "
    "Lider Chile listings when possible. "
    f"Respond with a single JSON array only — no markdown, no code fences, no text before or after. "
    f"The array must have at most {FIND_PRODUCTS_MAX} elements. Each element is one JSON object with the "
    "same keys and rules as for a single-product response: "
    '"display_name" (string: best retail-style product title for lists: proper capitalization, '
    "brand + product line + key format as on shelf or líder.cl; Spanish Chile; empty if unknown), "
    '"standard_name" (string: generic product type for grouping across brands and formats: Spanish Chile; '
    "omit marca, precio, and envase/tamaño; short noun phrase e.g. \"Leche entera\", \"Arroz grano largo\"; "
    "empty if unknown), "
    '"brand" (string: marca comercial or empty), '
    '"price" (number: typical shelf price in Chilean pesos CLP as a plain number — integer pesos, '
    "no thousands separators, no currency symbol; e.g. 3990 for a shelf label like $3.990; use 0 if unknown), "
    '"format" (string: presentation: size, units, e.g. "1 L", "6 x 330 ml", "500 g"; empty if unknown), '
    '"emoji" (string: one Unicode emoji best matching product type or category, e.g. 🥛 for milk, 🍚 for rice; '
    "empty string \"\" if unsure). "
    "Use empty string \"\" for unknown string fields. Use 0 for unknown price. "
    "Do not repeat the same líder.cl SKU or identical display_name twice. Prefer distinct products."
)

LIDER_PRODUCT_SYSTEM_INSTRUCTION = (
    "You help catalog grocery products sold in Chile at Lider (Walmart Chile), website líder.cl. "
    "Use Google Search to find how this product appears on líder.cl or in Lider Chile listings "
    "when possible. "
    "Respond with a single JSON object only — no markdown, no code fences, no text before or after. "
    'Keys: "display_name" (string: best retail-style product title for lists: proper capitalization, '
    "brand + product line + key format as on shelf or líder.cl; Spanish Chile; empty if unknown), "
    '"standard_name" (string: generic product type for grouping across brands and formats: Spanish Chile; '
    "omit marca, precio, and envase/tamaño; short noun phrase e.g. \"Leche entera\", \"Arroz grano largo\"; "
    "empty if unknown), "
    '"brand" (string: marca comercial or empty), '
    '"price" (number: typical shelf price in Chilean pesos CLP as a plain number — integer pesos, '
    "no thousands separators, no currency symbol; e.g. 3990 for a shelf label like $3.990; use 0 if unknown), "
    '"format" (string: presentation: size, units, e.g. "1 L", "6 x 330 ml", "500 g"; empty if unknown), '
    '"emoji" (string: one Unicode emoji best matching product type or category, e.g. 🥛 for milk, 🍚 for rice; '
    "empty string \"\" if unsure). "
    "Use empty string \"\" for unknown string fields. Use 0 for unknown price."
)


@dataclass(frozen=True)
class LiderProductInfo:
    display_name: str
    standard_name: str
    brand: str
    price: Decimal
    format: str
    emoji: str


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


def _lider_product_info_from_mapping(data: dict[str, Any]) -> LiderProductInfo:
    return LiderProductInfo(
        display_name=_normalize_field(data.get("display_name"), 255),
        standard_name=_normalize_field(data.get("standard_name"), 255),
        brand=_normalize_field(data.get("brand"), 255),
        price=_parse_price_value(data.get("price")),
        format=_normalize_field(data.get("format"), 255),
        emoji=_normalize_field(data.get("emoji"), 64),
    )


def _parse_lider_product_payload(raw: str | None) -> LiderProductInfo | None:
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
    return _lider_product_info_from_mapping(data)


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


def _parse_lider_product_list_payload(
    raw: str | None,
    *,
    max_items: int,
) -> list[LiderProductInfo]:
    """Parse model output into zero or more structured products; cap at *max_items*."""
    if not raw or max_items < 1:
        return []
    blob = _extract_json_array(raw)
    if not blob:
        single = _parse_lider_product_payload(raw)
        return [single] if single else []
    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        single = _parse_lider_product_payload(raw)
        return [single] if single else []
    if isinstance(data, dict) and "products" in data and isinstance(data["products"], list):
        data = data["products"]
    elif isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        return []
    out: list[LiderProductInfo] = []
    for item in data:
        if len(out) >= max_items:
            break
        if not isinstance(item, dict):
            continue
        out.append(_lider_product_info_from_mapping(item))
    return out


def fetch_lider_product_info(*, product_name: str) -> LiderProductInfo | None:
    """Ask Gemini (with Google Search) for Chile/Líder-oriented structured product info."""
    name = (product_name or "").strip()
    if not name:
        return None

    prompt = (
        f"Product name (as entered by user): {name!r}\n\n"
        "Search and fill the JSON for this or the closest líder.cl / Lider Chile match."
    )

    client = _get_client()
    grounding = types.Tool(google_search=types.GoogleSearch())
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=LIDER_PRODUCT_SYSTEM_INSTRUCTION,
            temperature=0.25,
            tools=[grounding],
        ),
    )
    return _parse_lider_product_payload(response.text)


def fetch_lider_product_candidates(
    *,
    query: str,
    max_products: int = FIND_PRODUCTS_MAX,
) -> list[LiderProductInfo]:
    """Ask Gemini for up to *max_products* distinct Líder-oriented product rows for *query*."""
    name = (query or "").strip()
    if not name:
        return []
    lim = max(1, min(max_products, FIND_PRODUCTS_MAX))

    prompt = (
        f"Product search query (as entered by user): {name!r}\n\n"
        f"Search líder.cl / Lider Chile and return up to {lim} distinct matching products as the "
        "JSON array described in the system instruction."
    )

    client = _get_client()
    grounding = types.Tool(google_search=types.GoogleSearch())
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=LIDER_PRODUCT_FIND_SYSTEM_INSTRUCTION,
            temperature=0.25,
            tools=[grounding],
        ),
    )
    return _parse_lider_product_list_payload(response.text, max_items=lim)
