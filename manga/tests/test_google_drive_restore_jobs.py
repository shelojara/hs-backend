"""Google Drive series restore (django-q2 + local filesystem)."""

import os
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model

from manga.models import (
    GoogleDriveBackupJobStatus,
    GoogleDriveRestoreJob,
    Series,
    SeriesItem,
)
from manga.services import (
    create_google_drive_restore_job,
    get_google_drive_restore_job,
    list_google_drive_restore_jobs,
    run_google_drive_restore_job,
)

User = get_user_model()


@pytest.mark.django_db
@patch("manga.services.async_task")
def test_create_google_drive_restore_job_persists_pending_and_enqueues(mock_async, tmp_path):
    root = tmp_path / "lib"
    root.mkdir()
    abs_root = str(root.resolve())
    s = Series.objects.create(library_root=abs_root, series_rel_path="s", name="s")
    (root / "s").mkdir()
    SeriesItem.objects.create(
        series=s,
        rel_path="s/x.cbz",
        filename="x.cbz",
        size_bytes=1,
    )
    u = User.objects.create_user(username="gdr_u1", password="pw")

    jid = create_google_drive_restore_job(
        manga_root=str(root),
        series_id=s.pk,
        user_id=u.pk,
    )
    j = GoogleDriveRestoreJob.objects.get(pk=jid)
    assert j.user_id == u.pk
    assert j.manga_root == abs_root
    assert j.series_id == s.pk
    assert j.status == GoogleDriveBackupJobStatus.PENDING
    mock_async.assert_called_once_with(
        "manga.scheduled_tasks.run_google_drive_restore_job",
        jid,
        task_name=f"manga_gdrive_restore:{jid}",
    )


@pytest.mark.django_db
@patch("manga.services.sync_series_items_for_series")
@patch("manga.services.download_drive_file_to_path")
@patch(
    "manga.services.list_drive_files_in_folder_meta",
    return_value=[("fid1", "a.cbz", 3)],
)
@patch("manga.services.get_series_drive_folder_id_optional", return_value="folder123")
def test_run_google_drive_restore_job_downloads_and_completes(
    _mock_folder,
    _mock_list,
    mock_download,
    _mock_sync,
    tmp_path,
):
    root = tmp_path / "lib"
    root.mkdir()
    abs_root = str(root.resolve())
    s = Series.objects.create(library_root=abs_root, series_rel_path="s", name="s")
    (root / "s").mkdir()
    u = User.objects.create_user(username="gdr_u2", password="pw")
    job = GoogleDriveRestoreJob.objects.create(
        user=u,
        manga_root=abs_root,
        series=s,
    )

    run_google_drive_restore_job(job_id=job.pk)

    job.refresh_from_db()
    assert job.status == GoogleDriveBackupJobStatus.COMPLETED
    assert job.restored_file_count == 1
    assert job.failure_message is None
    mock_download.assert_called_once()
    _args, kwargs = mock_download.call_args
    assert kwargs["file_id"] == "fid1"
    assert kwargs["dest_path"].endswith(f"{os.sep}s{os.sep}a.cbz")
    _mock_sync.assert_called_once_with(manga_root=abs_root, series_id=s.pk)


@pytest.mark.django_db
@patch("manga.services.get_series_drive_folder_id_optional", return_value=None)
def test_run_google_drive_restore_job_fails_when_no_drive_folder(_mock_folder, tmp_path):
    root = tmp_path / "lib"
    root.mkdir()
    abs_root = str(root.resolve())
    s = Series.objects.create(library_root=abs_root, series_rel_path="s", name="s")
    u = User.objects.create_user(username="gdr_u3", password="pw")
    job = GoogleDriveRestoreJob.objects.create(
        user=u,
        manga_root=abs_root,
        series=s,
    )

    run_google_drive_restore_job(job_id=job.pk)

    job.refresh_from_db()
    assert job.status == GoogleDriveBackupJobStatus.FAILED
    assert "Series folder not found" in (job.failure_message or "")


@pytest.mark.django_db
def test_get_google_drive_restore_job_owner(tmp_path):
    root = tmp_path / "lib"
    root.mkdir()
    abs_root = str(root.resolve())
    s = Series.objects.create(library_root=abs_root, series_rel_path="s", name="s")
    u = User.objects.create_user(username="gdr_u4", password="pw")
    job = GoogleDriveRestoreJob.objects.create(
        user=u,
        manga_root=abs_root,
        series=s,
    )
    got = get_google_drive_restore_job(job_id=job.pk, user_id=u.pk)
    assert got.pk == job.pk


@pytest.mark.django_db
def test_list_google_drive_restore_jobs_invalid_status_raises(tmp_path):
    root = tmp_path / "lib"
    root.mkdir()
    u = User.objects.create_user(username="gdr_u5", password="pw")
    with pytest.raises(ValueError, match="Invalid status filter"):
        list_google_drive_restore_jobs(
            manga_root=str(root),
            series_id=1,
            user_id=u.pk,
            status="bogus",
        )
