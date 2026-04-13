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

INSIGHTS_SYSTEM_INSTRUCTION = (
    "You infer what a web page is about from its visible text snapshot (URL is weak context only). "
    "Ground every claim in the snapshot; never invent prices, genres, or availability. "
    "Field page_kind: one short snake_case label for the dominant page type "
    "(e.g. ecommerce_product, news_article, documentation, blog_post, manga_series, anime_streaming, "
    "forum_thread, landing_marketing, other). "
    "Field about: one or two sentences on the main topic or purpose—concrete, not generic marketing fluff. "
    "Field highlights: exactly three objects, ordered most useful first for a human skimming the page. "
    "Each object: label = short snake_case facet name; value = one tight phrase copied or paraphrased "
    "strictly from visible text (include currency with price when both appear). "
    "The three highlights must be three different facets (no duplicate labels; do not repeat page_kind "
    "as a label). "
    "Choose the three facts that best disambiguate this page vs similar pages: "
    "e-commerce → prefer price, product_category or product_name, then stock/seller/rating/size only if "
    "clearly in text; manga/anime/media → prefer genre, series_title or work_title, then author/studio/"
    "volume_chapter/format/rating whichever is most specific in the text; news/blog → headline angle, "
    "entity, date or section; docs → product or topic, audience, version if stated. "
    "Always output exactly three highlights; if a third strong facet is missing, pick the next-best "
    "distinct facet still grounded in the text (e.g. site_section, language, content_format). "
    "Use an empty value string only when the label applies but the snapshot has no corresponding string."
)


class SnapshotHighlight(BaseModel):
    label: str = Field(min_length=1, max_length=64)
    value: str = Field(max_length=512)


class SnapshotContentInsightsResponse(BaseModel):
    about: str = Field(min_length=1, max_length=1200)
    page_kind: str = Field(min_length=1, max_length=120)
    highlights: list[SnapshotHighlight] = Field(default_factory=list, max_length=3)


def _get_client() -> genai.Client:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY environment variable is not set. "
            "Please set it to a valid Gemini API key."
        )
    return genai.Client(api_key=api_key)


def extract_content_insights(*, page_url: str, text: str) -> dict:
    """Ask Gemini for structured page summary; empty dict if unavailable or on failure."""
    if not os.environ.get("GEMINI_API_KEY"):
        return {}

    snippet = (text or "")[:_FEATURE_TEXT_MAX_CHARS]
    if not snippet.strip():
        return {}

    prompt = (
        f"## Page URL\n\n{page_url}\n\n"
        f"## Snapshot text (may be truncated)\n\n{snippet}\n\n"
        "## Task\n\n"
        "Return JSON: about, page_kind, highlights. "
        "highlights must be an array of exactly three {label, value} objects, "
        "ordered by importance, following the system rules."
    )

    try:
        client = _get_client()
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=INSIGHTS_SYSTEM_INSTRUCTION,
                temperature=0.3,
                response_mime_type="application/json",
                response_schema=SnapshotContentInsightsResponse,
            ),
        )
        parsed = response.parsed
        if isinstance(parsed, SnapshotContentInsightsResponse):
            return _insights_to_dict(parsed)
        if isinstance(parsed, dict):
            normalized = _normalize_insights_dict(parsed)
            if normalized:
                return normalized
        text_out = response.text
        if text_out:
            data = json.loads(text_out)
            normalized = _normalize_insights_dict(data)
            if normalized:
                return normalized
    except Exception:
        logger.exception("Gemini snapshot content insights extraction failed")

    return {}


def _insights_to_dict(parsed: SnapshotContentInsightsResponse) -> dict:
    return {
        "about": parsed.about.strip(),
        "page_kind": _normalize_page_kind(parsed.page_kind),
        "highlights": _normalize_highlights(
            [{"label": h.label, "value": h.value} for h in parsed.highlights]
        ),
    }


def _normalize_page_kind(raw: str) -> str:
    s = (raw or "").strip().lower().replace(" ", "_")
    s = "_".join(p for p in s.split("_") if p)
    return s[:120] if s else "other"


def _normalize_highlights(items: list) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        label = item.get("label")
        value = item.get("value")
        if not isinstance(label, str):
            continue
        label_key = _normalize_page_kind(label.replace(".", "_"))
        if not label_key or label_key in seen:
            continue
        val = value.strip() if isinstance(value, str) else ""
        if len(val) > 512:
            val = val[:509] + "..."
        out.append({"label": label_key, "value": val})
        seen.add(label_key)
        if len(out) >= 3:
            break
    return out


def _normalize_insights_dict(data: dict) -> dict:
    about = data.get("about")
    page_kind = data.get("page_kind")
    highlights = data.get("highlights")
    if not isinstance(about, str) or not about.strip():
        return {}
    if not isinstance(page_kind, str) or not page_kind.strip():
        page_kind = "other"
    hl: list = highlights if isinstance(highlights, list) else []
    return {
        "about": about.strip()[:1200],
        "page_kind": _normalize_page_kind(page_kind),
        "highlights": _normalize_highlights(hl),
    }


def legacy_feature_tags_from_insights(insights: dict) -> list[str]:
    """Up to three short tokens for older clients that only read features."""
    raw: list[str] = []
    pk = insights.get("page_kind")
    if isinstance(pk, str) and pk.strip():
        raw.append(pk.replace("_", " "))
    for h in (insights.get("highlights") or [])[:3]:
        if isinstance(h, dict) and isinstance(h.get("label"), str):
            raw.append(h["label"].replace("_", " "))
    return _normalize_feature_words(raw)[:3]


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
