import logging
import os

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

LIDER_PRODUCT_SYSTEM_INSTRUCTION = (
    "You help catalog grocery products sold in Chile at Lider (Walmart Chile), website líder.cl. "
    "Use Google Search to find how this product appears on líder.cl or in Lider Chile listings "
    "when possible. Summarize in Spanish (Chile): typical presentation (brand, size, format), "
    "category aisle, and one or two concrete facts if known. "
    "If you find no líder.cl-specific hit, say briefly that results are general Chile retail "
    "or uncertain. Plain text only: no markdown, no bullet characters, at most two short paragraphs, "
    "under 900 characters total."
)


def _get_client() -> genai.Client:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        msg = (
            "GEMINI_API_KEY environment variable is not set. "
            "Please set it to a valid Gemini API key."
        )
        raise RuntimeError(msg)
    return genai.Client(api_key=api_key)


def _normalize_details(raw: str | None) -> str | None:
    if not raw:
        return None
    text = " ".join((raw or "").split())
    if not text:
        return None
    if len(text) > 4000:
        text = text[:3997].rstrip() + "..."
    return text


def fetch_lider_product_details(*, product_name: str) -> str | None:
    """Ask Gemini (with Google Search) for Chile/Líder-oriented facts about *product_name*."""
    name = (product_name or "").strip()
    if not name:
        return None

    prompt = (
        f"Product name (as entered by user): {name!r}\n\n"
        "Search and report what líder.cl or Lider Chile lists for this or the closest match."
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
    return _normalize_details(response.text)
