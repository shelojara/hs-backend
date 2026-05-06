"""Google Drive restore: list backup folders vs local gaps + async download."""

import posixpath
from pathlib import Path
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model

from manga.models import GoogleDriveRestoreJob, GoogleDriveRestoreJobStatus, Series
from manga.tests.helpers import series_for_library_root
from manga.services import (
    create_google_drive_restore_job,
    get_google_drive_restore_job,
    list_google_drive_restore_candidates,
    run_google_drive_restore_job,
)

User = get_user_model()


@pytest.mark.django_db
@patch("manga.services.list_drive_cbz_files_in_folder")
@patch("manga.services.list_child_folder_names_and_ids")
@patch("manga.services.get_manga_root_drive_folder_id_optional")
def test_list_restore_candidates_counts_missing_across_categories(
    mock_root_id,
    mock_children,
    mock_cbzs,
    tmp_path,
):
    """Gap uses series name only: file under any matching ``Series`` row counts present."""
    root = tmp_path / "lib"
    root.mkdir()
    abs_root = str(root.resolve())
    mock_root_id.return_value = "manga_folder"

    mock_children.return_value = [("fold_a", "Alpha")]
    mock_cbzs.return_value = [
        {"id": "x1", "name": "a.cbz", "size": 10},
        {"id": "x2", "name": "b.cbz", "size": 20},
    ]

    series_for_library_root(
        abs_root,
        series_rel_path=posixpath.join("manga", "Alpha"),
        name="Alpha",
    )
    a_path = root / "manga" / "Alpha" / "a.cbz"
    a_path.parent.mkdir(parents=True)
    a_path.write_bytes(b"x" * 10)

    rows = list_google_drive_restore_candidates(manga_root=str(root))
    assert len(rows) == 1
    assert rows[0]["series_name"] == "Alpha"
    assert rows[0]["missing_files"] == 1
    assert rows[0]["exists_locally"] is True


@pytest.mark.django_db
@patch("manga.services.list_drive_cbz_files_in_folder")
@patch("manga.services.list_child_folder_names_and_ids")
@patch("manga.services.get_manga_root_drive_folder_id_optional")
def test_list_restore_invalid_drive_folder_name_all_missing(
    mock_root_id,
    mock_children,
    mock_cbzs,
    tmp_path,
):
    root = tmp_path / "lib"
    root.mkdir()
    mock_root_id.return_value = "manga_folder"
    mock_children.return_value = [("fold_b", "Bad/Name")]
    mock_cbzs.return_value = [{"id": "y1", "name": "only.cbz", "size": 5}]

    rows = list_google_drive_restore_candidates(manga_root=str(root))
    assert rows[0]["missing_files"] == 1
    assert rows[0]["exists_locally"] is False


@pytest.mark.django_db
@patch("manga.services.async_task")
@patch("manga.services.list_drive_cbz_files_in_folder")
@patch("manga.services.get_series_drive_folder_id_optional", return_value="sfold")
def test_create_restore_job_enqueues(_mock_folder, mock_list_cbz, mock_async, tmp_path):
    root = tmp_path / "lib"
    root.mkdir()
    mock_list_cbz.return_value = [{"id": "f1", "name": "c.cbz", "size": 1}]
    u = User.objects.create_user(username="gr_u1", password="pw")
    jid = create_google_drive_restore_job(
        manga_root=str(root),
        series_name="  MySeries  ",
        category="manga",
        user_id=u.pk,
    )
    job = GoogleDriveRestoreJob.objects.get(pk=jid)
    assert job.status == GoogleDriveRestoreJobStatus.PENDING
    assert job.series_name == "MySeries"
    assert job.category == "manga"
    mock_async.assert_called_once_with(
        "manga.scheduled_tasks.run_google_drive_restore_job",
        jid,
        task_name=f"manga_gdrive_restore:{jid}",
    )


@pytest.mark.django_db
def test_create_restore_job_empty_category_raises(tmp_path):
    root = tmp_path / "lib"
    root.mkdir()
    u = User.objects.create_user(username="gr_u_cat", password="pw")
    with pytest.raises(ValueError, match="category must be non-empty"):
        create_google_drive_restore_job(
            manga_root=str(root),
            series_name="S",
            category="   ",
            user_id=u.pk,
        )


@pytest.mark.django_db
@patch("manga.services.get_series_drive_folder_id_optional", return_value=None)
def test_create_restore_job_no_drive_folder_raises(_mock_opt, tmp_path):
    root = tmp_path / "lib"
    root.mkdir()
    u = User.objects.create_user(username="gr_u2", password="pw")
    with pytest.raises(ValueError, match="Series not found on Google Drive"):
        create_google_drive_restore_job(
            manga_root=str(root),
            series_name="Nope",
            category="manga",
            user_id=u.pk,
        )


@pytest.mark.django_db
@patch("manga.services.sync_series_items_for_series")
@patch("manga.services.download_drive_file_to_path")
@patch("manga.services.list_drive_cbz_files_in_folder")
@patch("manga.services.get_series_drive_folder_id_optional", return_value="fold_z")
def test_run_restore_job_downloads_and_creates_series(
    _fold,
    mock_list_cbz,
    mock_download,
    mock_sync,
    tmp_path,
):
    root = tmp_path / "lib"
    root.mkdir()
    abs_root = str(root.resolve())
    mock_list_cbz.return_value = [
        {"id": "id1", "name": "one.cbz", "size": 3},
    ]

    def download_side_effect(*, file_id: str, dest_path: str) -> None:
        Path(dest_path).write_bytes(b"cbz")

    mock_download.side_effect = download_side_effect
    u = User.objects.create_user(username="gr_u3", password="pw")
    job = GoogleDriveRestoreJob.objects.create(
        user=u,
        manga_root=abs_root,
        series_name="Restored",
        category="manga",
    )

    run_google_drive_restore_job(job_id=job.pk)

    job.refresh_from_db()
    assert job.status == GoogleDriveRestoreJobStatus.COMPLETED
    assert job.failure_message is None
    out = root / "manga" / "Restored" / "one.cbz"
    assert out.is_file()
    mock_download.assert_called_once()
    assert mock_sync.called
    s = Series.objects.get(
        library__fs_path=abs_root,
        series_rel_path=posixpath.join("manga", "Restored"),
    )
    assert s.name == "Restored"


@pytest.mark.django_db
def test_get_google_drive_restore_job_owner(tmp_path):
    root = tmp_path / "lib"
    root.mkdir()
    abs_root = str(root.resolve())
    u = User.objects.create_user(username="gr_u4", password="pw")
    job = GoogleDriveRestoreJob.objects.create(
        user=u,
        manga_root=abs_root,
        series_name="X",
        category="manga",
    )
    got = get_google_drive_restore_job(job_id=job.pk, user_id=u.pk)
    assert got.pk == job.pk
