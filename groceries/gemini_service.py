import json
import logging
import os
import re
from dataclasses import dataclass

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

LIDER_PRODUCT_SYSTEM_INSTRUCTION = (
    "You help catalog grocery products sold in Chile at Lider (Walmart Chile), website líder.cl. "
    "Use Google Search to find how this product appears on líder.cl or in Lider Chile listings "
    "when possible. "
    "Respond with a single JSON object only — no markdown, no code fences, no text before or after. "
    'Keys (all strings): "display_name" (best retail-style product title for lists: proper capitalization, '
    "brand + product line + key format as on shelf or líder.cl; Spanish Chile; empty if unknown), "
    '"brand" (marca comercial or empty), '
    '"price" (typical shelf price in Chilean pesos or CLP text as found, or empty if unknown), '
    '"format" (presentation: size, units, e.g. "1 L", "6 x 330 ml", "500 g"; empty if unknown), '
    '"details" (one short paragraph in Spanish (Chile): category/aisle and one concrete fact if known; '
    "if no líder.cl hit, say briefly that results are general or uncertain). "
    "Use empty string \"\" for any unknown field. "
    "Keep \"details\" under 900 characters."
)


@dataclass(frozen=True)
class LiderProductInfo:
    display_name: str
    brand: str
    price: str
    format: str
    details: str


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


def _parse_lider_product_payload(raw: str | None) -> LiderProductInfo | None:
    """Parse model output into structured fields; fallback prose → details only."""
    if not raw:
        return None
    blob = _extract_json_object(raw)
    if blob:
        try:
            data = json.loads(blob)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict):
            return LiderProductInfo(
                display_name=_normalize_field(data.get("display_name"), 255),
                brand=_normalize_field(data.get("brand"), 255),
                price=_normalize_field(data.get("price"), 128),
                format=_normalize_field(data.get("format"), 255),
                details=_normalize_field(data.get("details"), 4000),
            )
    # Legacy: plain text → details only
    details = _normalize_field(raw, 4000)
    if not details:
        return None
    return LiderProductInfo(
        display_name="",
        brand="",
        price="",
        format="",
        details=details,
    )


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
