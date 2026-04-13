import json
import logging
import os

from google import genai
from google.genai import types
from pydantic import BaseModel, Field

from pagechecker.models import Snapshot

logger = logging.getLogger(__name__)

# Bound prompt size for feature extraction (plain-text body snapshot).
_FEATURE_TEXT_MAX_CHARS = 12_000


def _developer_api_key() -> str | None:
    """Key for Gemini Developer API.

    google-genai documents `GOOGLE_API_KEY`; this app historically used
    `GEMINI_API_KEY`. Accept both so env matches SDK / deployment docs.
    """
    return os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")


def _response_visible_text(response: object) -> str | None:
    """Concatenate model text parts, skipping thought/reasoning parts.

    `GenerateContentResponse.text` omits parts with ``thought=True``; for
    thinking models the JSON answer can live only in later parts, leaving
    ``response.text`` empty and breaking schema parsing.
    """
    candidates = getattr(response, "candidates", None)
    if not candidates:
        return None
    content = candidates[0].content
    if content is None or not content.parts:
        return None
    chunks: list[str] = []
    for part in content.parts:
        text = getattr(part, "text", None)
        if not isinstance(text, str) or not text:
            continue
        if getattr(part, "thought", None) is True:
            continue
        chunks.append(text)
    return "".join(chunks) if chunks else None

SYSTEM_INSTRUCTION = (
    "You are an expert at analysing web-page content snapshots. "
    "The user will provide two snapshots of the same page taken at different times "
    "and then ask a question about the differences or similarities between them. "
    "Answer concisely and accurately based only on the provided snapshots."
)

SINGLE_SNAPSHOT_SYSTEM_INSTRUCTION = (
    "You are an expert at analysing web-page content snapshots. "
    "The user will provide one snapshot of a page and ask a question about it. "
    "Answer concisely and accurately based only on the provided snapshot."
)

FEATURES_SYSTEM_INSTRUCTION = (
    "You summarise a web page's visible text snapshot. "
    "Return exactly three short content descriptors: concrete phrases about "
    "what the page offers or covers (e.g. 'wireless earbuds', 'free shipping', "
    "'api documentation'). Prefer noun phrases over mood "
    "adjectives like 'professional' or 'minimal'. "
    "If the snapshot clearly states a product or service price (including "
    "currency symbol or code), use one of the three slots for that price "
    "exactly as written in the snapshot (normalise only obvious whitespace). "
    "If no price is present, all three must be non-price content descriptors. "
    "Base every item only on the snapshot text. No duplicates; trim whitespace; "
    "each item at most 3 words."
)


class SnapshotFeaturesResponse(BaseModel):
    features: list[str] = Field(min_length=3, max_length=3)


def _get_client() -> genai.Client:
    api_key = _developer_api_key()
    if not api_key:
        raise RuntimeError(
            "No Gemini API key found. Set GEMINI_API_KEY or GOOGLE_API_KEY "
            "to a valid Gemini Developer API key."
        )
    return genai.Client(api_key=api_key)


def _features_from_parsed(parsed: object) -> list[str] | None:
    if isinstance(parsed, SnapshotFeaturesResponse):
        return _normalize_features(parsed.features)
    if isinstance(parsed, dict):
        raw = parsed.get("features", [])
        if isinstance(raw, list):
            return _normalize_features(raw)
    return None


def extract_snapshot_features(*, page_url: str, text: str) -> list[str]:
    """Ask Gemini for three content descriptors (price slot if visible); empty if unavailable."""
    if not _developer_api_key():
        return []

    snippet = (text or "")[:_FEATURE_TEXT_MAX_CHARS]
    if not snippet.strip():
        return []

    prompt = (
        f"## Page URL\n\n{page_url}\n\n"
        f"## Snapshot text (may be truncated)\n\n{snippet}\n\n"
        "## Task\n\n"
        "Return exactly three content descriptors (and include a clear price in "
        "one slot when the snapshot shows one), as specified in the system instruction."
    )

    try:
        client = _get_client()
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=FEATURES_SYSTEM_INSTRUCTION,
                temperature=0.3,
                response_mime_type="application/json",
                response_schema=SnapshotFeaturesResponse,
            ),
        )
        normalized = _features_from_parsed(response.parsed)
        if normalized:
            return normalized

        json_text = _response_visible_text(response) or response.text
        if json_text:
            try:
                model = SnapshotFeaturesResponse.model_validate_json(json_text)
            except Exception:
                try:
                    data = json.loads(json_text)
                except json.JSONDecodeError:
                    logger.warning(
                        "Gemini features: response was not valid JSON (first 200 chars): %r",
                        json_text[:200],
                    )
                else:
                    raw = data.get("features", [])
                    if isinstance(raw, list):
                        return _normalize_features(raw)
            else:
                return _normalize_features(model.features)
    except Exception:
        logger.exception("Gemini snapshot feature extraction failed")

    return []


_FEATURE_ITEM_MAX_CHARS = 120
_FEATURE_ITEM_MAX_WORDS = 3


def _normalize_features(items: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in items:
        if not isinstance(raw, str):
            continue
        s = " ".join(raw.strip().split())
        if not s:
            continue
        words = s.split()
        if len(words) > _FEATURE_ITEM_MAX_WORDS:
            s = " ".join(words[:_FEATURE_ITEM_MAX_WORDS])
        if len(s) > _FEATURE_ITEM_MAX_CHARS:
            s = s[:_FEATURE_ITEM_MAX_CHARS].rstrip()
        key = s.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
        if len(out) >= 3:
            break
    return out[:3]


def compare_snapshots(
    snapshot_a_id: int,
    snapshot_b_id: int,
    question: str,
    *,
    use_html: bool = False,
) -> str:
    """Send two snapshots to Gemini and return its answer to *question*."""
    snapshot_a = Snapshot.objects.select_related("page").get(id=snapshot_a_id)
    snapshot_b = Snapshot.objects.select_related("page").get(id=snapshot_b_id)

    content_a = (
        snapshot_a.html_content or snapshot_a.content
        if use_html
        else snapshot_a.content
    )
    content_b = (
        snapshot_b.html_content or snapshot_b.content
        if use_html
        else snapshot_b.content
    )

    prompt = (
        f"## Snapshot A (id={snapshot_a.id}, taken {snapshot_a.created_at.isoformat()})\n\n"
        f"{content_a}\n\n"
        f"---\n\n"
        f"## Snapshot B (id={snapshot_b.id}, taken {snapshot_b.created_at.isoformat()})\n\n"
        f"{content_b}\n\n"
        f"---\n\n"
        f"## Question\n\n{question}"
    )

    client = _get_client()
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            temperature=0.3,
        ),
    )
    return response.text


def answer_question_about_snapshot(
    snapshot_id: int,
    question: str,
    *,
    use_html: bool = False,
) -> str:
    """Send one snapshot to Gemini and return its answer to *question*."""
    snapshot = Snapshot.objects.select_related("page").get(id=snapshot_id)
    content = (
        (snapshot.html_content or snapshot.content)
        if use_html
        else snapshot.content
    )

    prompt = (
        f"## Snapshot (id={snapshot.id}, taken {snapshot.created_at.isoformat()})\n\n"
        f"{content}\n\n"
        f"---\n\n"
        f"## Question\n\n{question}"
    )

    client = _get_client()
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=SINGLE_SNAPSHOT_SYSTEM_INSTRUCTION,
            temperature=0.3,
        ),
    )
    return response.text
