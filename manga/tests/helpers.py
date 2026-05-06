"""Shared test utilities for manga app."""

from __future__ import annotations

import os

from manga.models import MangaLibrary, Series


def series_for_library_root(abs_root: str, **series_fields) -> Series:
    """Create ``Series`` linked to ``MangaLibrary`` for *abs_root* (normalized path string)."""
    norm = os.path.abspath(os.path.expanduser(abs_root))
    lib, _created = MangaLibrary.objects.get_or_create(
        fs_path=norm,
        defaults={
            "name": (os.path.basename(norm.rstrip(os.sep)) or "Library")[:256],
        },
    )
    return Series.objects.create(library=lib, library_root=norm, **series_fields)
