"""Savings test harness: avoid real Gemini calls when GEMINI_API_KEY is set."""

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def stub_gemini_asset_emoji_outside_gemini_tests(request, monkeypatch):
    """create_asset() calls suggest_asset_emoji; network makes suite slow/flaky.

    test_gemini_service exercises suggest_asset_emoji with _get_client mocked.
    """
    if Path(request.node.path).name == "test_gemini_service.py":
        return
    monkeypatch.setattr(
        "savings.gemini_service.suggest_asset_emoji",
        lambda *, name: "",
    )
