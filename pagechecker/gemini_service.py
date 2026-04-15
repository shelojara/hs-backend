import logging
import os
import re

from google import genai
from google.genai import types

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

CATEGORY_EMOJI_SYSTEM_INSTRUCTION = (
    "You pick one Unicode emoji that best represents a short category label "
    "for organizing monitored web pages. Reply with exactly one emoji and no other text."
)

PAGE_CATEGORY_SYSTEM_INSTRUCTION = (
    "You assign monitored web pages to existing categories. Each category has a name "
    "and example pages (URL and title) already placed in that category. "
    "Pick the single category id that best fits the new page by matching topic, audience, "
    "and content type to those examples. If none fit, reply NONE. "
    "Output only: a decimal integer (one of the listed ids) or the word NONE. No punctuation, "
    "no explanation, no markdown."
)

_MAX_PAGE_CATEGORY_EXCERPT = 12_000


def _parse_category_id_choice(raw: str | None, valid_ids: set[int]) -> int | None:
    """Interpret Gemini reply as one of *valid_ids* or no assignment."""
    if not raw:
        return None
    t = raw.strip()
    if not t:
        return None
    head = t.splitlines()[0].strip().strip("\"'`")
    upper = head.upper()
    if upper in frozenset({"NONE", "NULL", "NO", "N/A", "UNSURE"}):
        return None
    try:
        n = int(head)
    except ValueError:
        m = re.search(r"\b(\d+)\b", t)
        if not m:
            return None
        n = int(m.group(1))
    return n if n in valid_ids else None


def _get_client() -> genai.Client:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY environment variable is not set. "
            "Please set it to a valid Gemini API key."
        )
    return genai.Client(api_key=api_key)


def compare_snapshots(
    snapshot_a_id: int,
    snapshot_b_id: int,
    question: str,
) -> str:
    """Send two snapshots to Gemini and return its answer to *question*."""
    snapshot_a = Snapshot.objects.select_related("page").get(id=snapshot_a_id)
    snapshot_b = Snapshot.objects.select_related("page").get(id=snapshot_b_id)

    content_a = snapshot_a.md_content or ""
    content_b = snapshot_b.md_content or ""

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
) -> str:
    """Send one snapshot to Gemini and return its answer to *question*."""
    snapshot = Snapshot.objects.select_related("page").get(id=snapshot_id)
    content = snapshot.md_content or ""

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


def suggest_category_emoji(category_name: str) -> str:
    """Ask Gemini for a single emoji representing *category_name*."""
    prompt = f"Category name: {category_name!r}\n\nSuggest one emoji for this category."

    client = _get_client()
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=CATEGORY_EMOJI_SYSTEM_INSTRUCTION,
            temperature=0.4,
        ),
    )
    text = (response.text or "").strip().strip("\"'")
    if not text:
        logger.warning("Gemini returned empty emoji for category %r", category_name)
        return "📁"
    return text[:64]


def suggest_page_category_id(
    *,
    page_url: str,
    page_title: str,
    page_content_excerpt: str,
    categories: list[dict],
) -> int | None:
    """Ask Gemini which existing category id fits *page_*; return None if NONE or invalid."""
    if not categories:
        return None
    valid_ids = {int(c["id"]) for c in categories}
    lines: list[str] = [
        "Existing categories — reply with exactly one id from the list below, or NONE.",
        "",
    ]
    for c in categories:
        cid = int(c["id"])
        name = str(c.get("name", ""))
        lines.append(f"### id={cid} name={name!r}")
        examples = c.get("examples") or []
        if examples:
            lines.append("Example pages already in this category:")
            for ex in examples:
                u = str(ex.get("url", ""))
                tit = str(ex.get("title", "")).strip() or "(no title)"
                lines.append(f"- {u} — {tit}")
        else:
            lines.append("(no example pages in this category yet)")
        lines.append("")
    excerpt = (page_content_excerpt or "")[:_MAX_PAGE_CATEGORY_EXCERPT]
    lines.extend(
        [
            "---",
            "New page to classify:",
            f"URL: {page_url}",
            f"Title: {page_title or '(none)'}",
            "",
            "Content excerpt (markdown, may be truncated):",
            excerpt if excerpt else "(empty)",
        ]
    )
    prompt = "\n".join(lines)

    client = _get_client()
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=PAGE_CATEGORY_SYSTEM_INSTRUCTION,
            temperature=0.2,
        ),
    )
    choice = _parse_category_id_choice(response.text, valid_ids)
    if choice is None and (response.text or "").strip():
        logger.warning(
            "Gemini page category reply not mapped to a category id: %r",
            (response.text or "")[:200],
        )
    return choice
