"""Shared helpers for manga tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from manga.models import MangaLibrary


def manga_library_for_path(*, filesystem_path: str | Path, name: str = "lib") -> MangaLibrary:
    """Create ``MangaLibrary`` at normalized *filesystem_path* (directory created)."""
    p = Path(filesystem_path).resolve()
    p.mkdir(parents=True, exist_ok=True)
    return MangaLibrary.objects.create(name=name, filesystem_path=str(p))


@pytest.fixture
def manga_user(db):
    """Auth user for job rows that still require ``user_id`` (convert/backup/restore)."""
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(username="manga_test_user", password="pw")
