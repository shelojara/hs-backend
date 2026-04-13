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
    "Pick exactly three short descriptors for the page: mostly single-word "
    "adjectives (e.g. technical, promotional, minimal). "
    "Base them only on the snapshot text. No punctuation in each word, "
    "no duplicates, lowercase."
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


def extract_snapshot_features(*, page_url: str, text: str) -> list[str]:
    """Ask Gemini for three descriptor words; empty list if unavailable or on failure."""
    if not os.environ.get("GEMINI_API_KEY"):
        return []

    snippet = (text or "")[:_FEATURE_TEXT_MAX_CHARS]
    if not snippet.strip():
        return []

    prompt = (
        f"## Page URL\n\n{page_url}\n\n"
        f"## Snapshot text (may be truncated)\n\n{snippet}\n\n"
        "## Task\n\n"
        "Return exactly three descriptors as specified in the system instruction."
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
            return _normalize_feature_words(parsed.features)
        if isinstance(parsed, dict):
            raw = parsed.get("features", [])
            if isinstance(raw, list):
                return _normalize_feature_words(raw)
        text_out = response.text
        if text_out:
            data = json.loads(text_out)
            raw = data.get("features", [])
            if isinstance(raw, list):
                return _normalize_feature_words(raw)
    except Exception:
        logger.exception("Gemini snapshot feature extraction failed")

    return []


def _normalize_feature_words(words: list[str]) -> list[str]:
    out: list[str] = []
    for w in words:
        if not isinstance(w, str):
            continue
        s = w.strip().lower().replace("-", " ")
        s = " ".join(s.split())
        if not s:
            continue
        if " " in s:
            s = s.split()[0]
        if s and s not in out:
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
