import json
import logging
import os

from google import genai
from google.genai import types
from pydantic import BaseModel, Field

from pagechecker.models import Snapshot

logger = logging.getLogger(__name__)

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
    "You summarise a web page from its body HTML (scripts/styles already removed). "
    "Infer visible meaning from structure and text nodes. "
    "Return exactly three short content descriptors: concrete phrases about "
    "what the page offers or covers (e.g. 'wireless earbuds', 'free shipping', "
    "'api documentation'). Prefer noun phrases over mood "
    "adjectives like 'professional' or 'minimal'. "
    "If the page clearly states a product or service price (including "
    "currency symbol or code), use one of the three slots for that price "
    "exactly as written in the content (normalise only obvious whitespace). "
    "If no price is present, all three must be non-price content descriptors. "
    "Base every item only on the provided HTML. No duplicates; trim whitespace; "
    "each item at most 3 words."
)


class SnapshotFeaturesResponse(BaseModel):
    features: list[str] = Field(min_length=3, max_length=3)


def _get_client() -> genai.Client:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY environment variable is not set. "
            "Please set it to a valid Gemini API key."
        )
    return genai.Client(api_key=api_key)


def extract_snapshot_features(*, page_url: str, html: str) -> list[str]:
    """Ask Gemini for three content descriptors (price slot if visible); empty if unavailable."""
    if not os.environ.get("GEMINI_API_KEY"):
        return []

    body_html = html or ""
    if not body_html.strip():
        return []

    prompt = (
        f"## Page URL\n\n{page_url}\n\n"
        f"## Body HTML\n\n{body_html}\n\n"
        "## Task\n\n"
        "Return exactly three content descriptors (and include a clear price in "
        "one slot when the page shows one), as specified in the system instruction."
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
        parsed = response.parsed
        if isinstance(parsed, SnapshotFeaturesResponse):
            return _normalize_features(parsed.features)
        if isinstance(parsed, dict):
            raw = parsed.get("features", [])
            if isinstance(raw, list):
                return _normalize_features(raw)
        text_out = response.text
        if text_out:
            data = json.loads(text_out)
            raw = data.get("features", [])
            if isinstance(raw, list):
                return _normalize_features(raw)
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
