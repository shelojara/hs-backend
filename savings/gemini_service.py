"""Gemini helpers for savings domain."""

import logging
import os

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

ASSET_EMOJI_SYSTEM_INSTRUCTION = (
    "You pick one Unicode emoji that best represents a personal savings goal or financial asset "
    "named by the user (may be short phrase in any language: vacation fund, emergency fund, etc.). "
    "Reply with exactly one emoji and no other text."
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


def suggest_asset_emoji(*, name: str) -> str:
    """Ask Gemini for one emoji representing savings asset *name*."""
    prompt = f"Savings goal name: {name.strip()!r}\n\nSuggest one emoji for this goal."

    client = _get_client()
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=ASSET_EMOJI_SYSTEM_INSTRUCTION,
            temperature=0.35,
        ),
    )
    text = (response.text or "").strip().strip("\"'")
    if not text:
        logger.warning("Gemini returned empty emoji for savings asset %r", name)
        return "💰"
    return text[:64]
