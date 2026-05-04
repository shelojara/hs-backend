"""Parallel backup workers must not duplicate same-named Drive folders (TOCTOU on find+create)."""

from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

import pytest

from manga.google_drive_service import ensure_series_drive_folder
from manga.models import GoogleDriveApplicationCredentials


class _FakeDriveChain:
    """Minimal Drive v3 ``files().list/create().execute()`` for folder ops."""

    def __init__(self, state: dict[tuple[str, str], str], create_counts: list[int]) -> None:
        self._state = state
        self._create_counts = create_counts
        self._pending_list_parent: str | None = None
        self._pending_list_name: str | None = None
        self._pending_create_parent: str | None = None
        self._pending_create_name: str | None = None

    def list(self, *, q: str, **_: object) -> _FakeDriveChain:
        # q contains name = '...' and parents clause — parse naïvely for test.
        if "mimeType = 'application/vnd.google-apps.folder'" not in q:
            raise AssertionError(f"unexpected list q: {q!r}")
        name_start = q.index("name = '") + len("name = '")
        name_end = q.index("'", name_start)
        name = q[name_start:name_end].replace("\\'", "'").replace("\\\\", "\\")
        pin = "and '"
        pstart = q.rindex(pin) + len(pin)
        pend = q.index("'", pstart)
        parent_id = q[pstart:pend]
        self._pending_list_parent = parent_id
        self._pending_list_name = name
        return self

    def create(self, *, body: dict[str, object], **_: object) -> _FakeDriveChain:
        self._pending_create_parent = str(body["parents"][0])
        self._pending_create_name = str(body["name"])
        return self

    def execute(self) -> dict[str, object]:
        if self._pending_list_parent is not None:
            key = (self._pending_list_parent, self._pending_list_name or "")
            fid = self._state.get(key)
            self._pending_list_parent = None
            self._pending_list_name = None
            if fid:
                return {"files": [{"id": fid, "name": key[1]}]}
            return {"files": []}
        if self._pending_create_parent is not None:
            key = (self._pending_create_parent, self._pending_create_name or "")
            self._create_counts[0] += 1
            new_id = f"id_{key[0]}_{key[1]}_{self._create_counts[0]}"
            self._state[key] = new_id
            self._pending_create_parent = None
            self._pending_create_name = None
            return {"id": new_id}
        raise AssertionError("execute without list or create")


@pytest.mark.django_db
def test_ensure_series_drive_folder_no_duplicate_folders_under_parallel_calls() -> None:
    GoogleDriveApplicationCredentials.objects.get_or_create(pk=1)
    state: dict[tuple[str, str], str] = {}
    create_counts = [0]

    def _fake_drive_service() -> MagicMock:
        svc = MagicMock()
        chain = _FakeDriveChain(state, create_counts)
        svc.files.return_value = chain
        return svc

    results: list[str] = []
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            results.append(ensure_series_drive_folder(series_name="My Series"))
        except BaseException as exc:
            errors.append(exc)

    with (
        patch("manga.google_drive_service._drive_service", _fake_drive_service),
        patch("manga.google_drive_service._drive_parent_for_root_folder", return_value="root"),
        patch("manga.google_drive_service._root_folder_name", return_value="Manga"),
    ):
        t1 = threading.Thread(target=worker)
        t2 = threading.Thread(target=worker)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

    assert not errors, errors
    assert results[0] == results[1]
    # root "Manga" + one series folder — not doubled by two workers
    assert create_counts[0] == 2
