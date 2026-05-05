"""Google Drive series restore (django-q2 + local filesystem)."""

import os
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model

from manga.models import (
    GOOGLE_DRIVE_RESTORE_PENDING_LOCK,
    GoogleDriveBackupJobStatus,
    GoogleDriveRestoreJob,
    Series,
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
    Series.objects.create(library_root=abs_root, series_rel_path="s", name="s")
    (root / "s").mkdir()
    u = User.objects.create_user(username="gdr_u1", password="pw")

    jid = create_google_drive_restore_job(
        manga_root=str(root),
        series_name="s",
        user_id=u.pk,
    )
    j = GoogleDriveRestoreJob.objects.get(pk=jid)
    assert j.user_id == u.pk
    assert j.manga_root == abs_root
    assert j.series_name == "s"
    assert j.status == GoogleDriveBackupJobStatus.PENDING
    assert j.pending_lock == 1
    mock_async.assert_called_once_with(
        "manga.scheduled_tasks.run_google_drive_restore_job",
        jid,
        task_name=f"manga_gdrive_restore:{jid}",
    )


@pytest.mark.django_db
@patch("manga.services.async_task")
def test_create_google_drive_restore_job_rejects_while_another_pending(mock_async, tmp_path):
    root = tmp_path / "lib"
    root.mkdir()
    abs_root = str(root.resolve())
    Series.objects.create(library_root=abs_root, series_rel_path="a", name="a")
    Series.objects.create(library_root=abs_root, series_rel_path="b", name="b")
    (root / "a").mkdir()
    (root / "b").mkdir()
    u = User.objects.create_user(username="gdr_u6", password="pw")
    create_google_drive_restore_job(
        manga_root=str(root),
        series_name="a",
        user_id=u.pk,
    )
    with pytest.raises(ValueError, match="Another restore is already in progress"):
        create_google_drive_restore_job(
            manga_root=str(root),
            series_name="b",
            user_id=u.pk,
        )
    assert mock_async.call_count == 1


@pytest.mark.django_db
@patch("manga.services.sync_manga_library_cache")
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
    mock_sync_lib,
    tmp_path,
):
    root = tmp_path / "lib"
    root.mkdir()
    abs_root = str(root.resolve())
    u = User.objects.create_user(username="gdr_u2", password="pw")
    job = GoogleDriveRestoreJob.objects.create(
        user=u,
        manga_root=abs_root,
        series_name="s",
        pending_lock=GOOGLE_DRIVE_RESTORE_PENDING_LOCK,
    )

    run_google_drive_restore_job(job_id=job.pk)

    job.refresh_from_db()
    assert job.status == GoogleDriveBackupJobStatus.COMPLETED
    assert job.restored_file_count == 1
    assert job.pending_lock == 0
    assert job.failure_message is None
    mock_download.assert_called_once()
    _args, kwargs = mock_download.call_args
    assert kwargs["file_id"] == "fid1"
    assert kwargs["dest_path"].endswith(f"{os.sep}s{os.sep}a.cbz")
    mock_sync_lib.assert_called_once_with(manga_root=abs_root)


@pytest.mark.django_db
@patch("manga.services.get_series_drive_folder_id_optional", return_value=None)
def test_run_google_drive_restore_job_fails_when_no_drive_folder(_mock_folder, tmp_path):
    root = tmp_path / "lib"
    root.mkdir()
    abs_root = str(root.resolve())
    u = User.objects.create_user(username="gdr_u3", password="pw")
    job = GoogleDriveRestoreJob.objects.create(
        user=u,
        manga_root=abs_root,
        series_name="s",
        pending_lock=GOOGLE_DRIVE_RESTORE_PENDING_LOCK,
    )

    run_google_drive_restore_job(job_id=job.pk)

    job.refresh_from_db()
    assert job.status == GoogleDriveBackupJobStatus.FAILED
    assert job.pending_lock == 0
    assert "Series folder not found" in (job.failure_message or "")


@pytest.mark.django_db
def test_get_google_drive_restore_job_owner(tmp_path):
    root = tmp_path / "lib"
    root.mkdir()
    abs_root = str(root.resolve())
    u = User.objects.create_user(username="gdr_u4", password="pw")
    job = GoogleDriveRestoreJob.objects.create(
        user=u,
        manga_root=abs_root,
        series_name="s",
    )
    got = get_google_drive_restore_job(job_id=job.pk, user_id=u.pk)
    assert got.pk == job.pk


@pytest.mark.django_db
@patch("manga.services.async_task")
def test_create_google_drive_restore_job_full_library_omits_series_name(mock_async, tmp_path):
    root = tmp_path / "lib"
    root.mkdir()
    u = User.objects.create_user(username="gdr_full", password="pw")
    jid = create_google_drive_restore_job(
        manga_root=str(root),
        series_name=None,
        user_id=u.pk,
    )
    j = GoogleDriveRestoreJob.objects.get(pk=jid)
    assert j.series_name is None
    assert j.pending_lock == 1
    mock_async.assert_called_once()


@pytest.mark.django_db
@patch("manga.services.sync_manga_library_cache")
@patch("manga.services.download_drive_file_to_path")
@patch(
    "manga.services.list_drive_files_in_folder_meta",
    return_value=[("fid1", "a.cbz", 3)],
)
@patch(
    "manga.services.list_series_folder_children_meta",
    return_value=[("sf1", "RestoredSeries", True)],
)
@patch("manga.services.get_manga_root_drive_folder_id_optional", return_value="manga_root_id")
def test_run_google_drive_restore_job_full_manga_folder(
    _mock_m_root,
    _mock_children,
    _mock_meta,
    mock_download,
    mock_sync_lib,
    tmp_path,
):
    root = tmp_path / "lib"
    root.mkdir()
    abs_root = str(root.resolve())
    u = User.objects.create_user(username="gdr_run_all", password="pw")
    job = GoogleDriveRestoreJob.objects.create(
        user=u,
        manga_root=abs_root,
        series_name=None,
        pending_lock=GOOGLE_DRIVE_RESTORE_PENDING_LOCK,
    )
    run_google_drive_restore_job(job_id=job.pk)
    job.refresh_from_db()
    assert job.status == GoogleDriveBackupJobStatus.COMPLETED
    assert job.restored_file_count == 1
    mock_download.assert_called_once()
    _, dl_kwargs = mock_download.call_args
    assert dl_kwargs["dest_path"].endswith(f"RestoredSeries{os.sep}a.cbz")
    mock_sync_lib.assert_called_once_with(manga_root=abs_root)


@pytest.mark.django_db
def test_list_google_drive_restore_jobs_filter_by_series_name(tmp_path):
    root = tmp_path / "lib"
    root.mkdir()
    abs_root = str(root.resolve())
    u = User.objects.create_user(username="gdr_list", password="pw")
    j_full = GoogleDriveRestoreJob.objects.create(
        user=u,
        manga_root=abs_root,
        series_name=None,
    )
    j_ser = GoogleDriveRestoreJob.objects.create(
        user=u,
        manga_root=abs_root,
        series_name="MySeries",
    )
    all_rows = list_google_drive_restore_jobs(
        manga_root=str(root),
        series_name=None,
        user_id=u.pk,
    )
    assert {r.pk for r in all_rows} == {j_full.pk, j_ser.pk}
    only_named = list_google_drive_restore_jobs(
        manga_root=str(root),
        series_name="MySeries",
        user_id=u.pk,
    )
    assert [r.pk for r in only_named] == [j_ser.pk]


@pytest.mark.django_db
def test_list_google_drive_restore_jobs_invalid_status_raises(tmp_path):
    root = tmp_path / "lib"
    root.mkdir()
    u = User.objects.create_user(username="gdr_u5", password="pw")
    with pytest.raises(ValueError, match="Invalid status filter"):
        list_google_drive_restore_jobs(
            manga_root=str(root),
            series_name=None,
            user_id=u.pk,
            status="bogus",
        )


@pytest.mark.django_db
def test_create_google_drive_restore_job_rejects_empty_series_name_string(tmp_path):
    root = tmp_path / "lib"
    root.mkdir()
    u = User.objects.create_user(username="gdr_empty", password="pw")
    with pytest.raises(ValueError, match="series_name must be non-empty"):
        create_google_drive_restore_job(
            manga_root=str(root),
            series_name="   ",
            user_id=u.pk,
        )
