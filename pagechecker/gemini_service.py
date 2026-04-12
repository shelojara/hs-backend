import os

from google import genai
from google.genai import types

from pagechecker.models import Snapshot

SYSTEM_INSTRUCTION = (
    "You are an expert at analysing web-page content snapshots. "
    "The user will provide two snapshots of the same page taken at different times "
    "and then ask a question about the differences or similarities between them. "
    "Answer concisely and accurately based only on the provided snapshots."
)


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
    *,
    use_html: bool = False,
) -> str:
    """Send two snapshots to Gemini and return its answer to *question*."""
    snapshot_a = Snapshot.objects.select_related("page").get(id=snapshot_a_id)
    snapshot_b = Snapshot.objects.select_related("page").get(id=snapshot_b_id)

    content_a = snapshot_a.html_content if use_html else snapshot_a.content
    content_b = snapshot_b.html_content if use_html else snapshot_b.content

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
