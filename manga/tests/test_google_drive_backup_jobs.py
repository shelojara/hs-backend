"""Async Google Drive backup jobs (django-q2 + row status)."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model

from manga.models import GoogleDriveBackupJob, GoogleDriveBackupJobStatus, Series, SeriesItem
from manga.services import (
    create_google_drive_backup_job,
    get_google_drive_backup_job,
    list_google_drive_backup_jobs,
    run_google_drive_backup_job,
)

User = get_user_model()


@pytest.mark.django_db
@patch("manga.services.async_task")
def test_create_google_drive_backup_job_persists_pending_and_enqueues(mock_async, tmp_path):
    root = tmp_path / "lib"
    root.mkdir()
    abs_root = str(root.resolve())
    s = Series.objects.create(library_root=abs_root, series_rel_path="s", name="s")
    row = SeriesItem.objects.create(
        series=s,
        rel_path="s/ch.cbz",
        filename="ch.cbz",
        size_bytes=1,
    )
    u = User.objects.create_user(username="gd_u1", password="pw")

    jid = create_google_drive_backup_job(
        manga_root=str(root),
        item_id=row.pk,
        user_id=u.pk,
    )
    job = GoogleDriveBackupJob.objects.get(pk=jid)
    assert job.user_id == u.pk
    assert job.manga_root == abs_root
    assert job.series_id == s.pk
    assert job.series_item_id == row.pk
    assert job.status == GoogleDriveBackupJobStatus.PENDING
    mock_async.assert_called_once_with(
        "manga.scheduled_tasks.run_google_drive_backup_job",
        jid,
        task_name=f"manga_gdrive_backup:{jid}",
    )


@pytest.mark.django_db
@patch("manga.services.upload_file_to_folder", return_value="file_xyz")
@patch("manga.services.ensure_series_drive_folder", return_value="folder_abc")
@patch("manga.services.resolve_cbz_download")
def test_run_google_drive_backup_job_success(
    mock_resolve,
    _mock_folder,
    _mock_upload,
    tmp_path,
):
    root = tmp_path / "lib"
    root.mkdir()
    abs_root = str(root.resolve())
    cbz = root / "s" / "ch.cbz"
    cbz.parent.mkdir()
    cbz.write_bytes(b"PK\x03\x04fake")
    s = Series.objects.create(library_root=abs_root, series_rel_path="s", name="s")
    row = SeriesItem.objects.create(
        series=s,
        rel_path="s/ch.cbz",
        filename="ch.cbz",
        size_bytes=1,
    )
    u = User.objects.create_user(username="gd_u2", password="pw")
    job = GoogleDriveBackupJob.objects.create(
        user=u,
        manga_root=abs_root,
        series=s,
        series_item_id=row.pk,
    )
    mock_resolve.return_value = SimpleNamespace(absolute_path=str(cbz), filename="ch.cbz")

    run_google_drive_backup_job(job_id=job.pk)

    job.refresh_from_db()
    assert job.status == GoogleDriveBackupJobStatus.COMPLETED, (job.status, job.failure_message)
    mock_resolve.assert_called_once_with(manga_root=abs_root, item_id=row.pk)
    assert job.completed_at is not None
    assert job.failure_message is None
    assert job.google_drive_file_id == "file_xyz"


@pytest.mark.django_db
@patch("manga.services.resolve_cbz_download", side_effect=RuntimeError("boom"))
def test_run_google_drive_backup_job_marks_failed(_mock_resolve, tmp_path):
    root = tmp_path / "lib"
    root.mkdir()
    abs_root = str(root.resolve())
    s = Series.objects.create(library_root=abs_root, series_rel_path="s", name="s")
    row = SeriesItem.objects.create(
        series=s,
        rel_path="s/ch.cbz",
        filename="ch.cbz",
        size_bytes=1,
    )
    u = User.objects.create_user(username="gd_u3", password="pw")
    job = GoogleDriveBackupJob.objects.create(
        user=u,
        manga_root=abs_root,
        series=s,
        series_item_id=row.pk,
    )

    run_google_drive_backup_job(job_id=job.pk)

    job.refresh_from_db()
    assert job.status == GoogleDriveBackupJobStatus.FAILED
    assert job.completed_at is not None
    assert job.failure_message == "boom"


@pytest.mark.django_db
def test_get_google_drive_backup_job_owner(tmp_path):
    root = tmp_path / "lib"
    root.mkdir()
    abs_root = str(root.resolve())
    s = Series.objects.create(library_root=abs_root, series_rel_path="s", name="s")
    row = SeriesItem.objects.create(
        series=s,
        rel_path="s/ch.cbz",
        filename="ch.cbz",
        size_bytes=1,
    )
    u = User.objects.create_user(username="gd_u5", password="pw")
    job = GoogleDriveBackupJob.objects.create(
        user=u,
        manga_root=abs_root,
        series=s,
        series_item_id=row.pk,
    )
    got = get_google_drive_backup_job(job_id=job.pk, user_id=u.pk)
    assert got.pk == job.pk


@pytest.mark.django_db
def test_get_google_drive_backup_job_wrong_user_raises(tmp_path):
    root = tmp_path / "lib"
    root.mkdir()
    abs_root = str(root.resolve())
    s = Series.objects.create(library_root=abs_root, series_rel_path="s", name="s")
    row = SeriesItem.objects.create(
        series=s,
        rel_path="s/ch.cbz",
        filename="ch.cbz",
        size_bytes=1,
    )
    u = User.objects.create_user(username="gd_u6", password="pw")
    other = User.objects.create_user(username="gd_u7", password="pw")
    job = GoogleDriveBackupJob.objects.create(
        user=u,
        manga_root=abs_root,
        series=s,
        series_item_id=row.pk,
    )
    with pytest.raises(GoogleDriveBackupJob.DoesNotExist):
        get_google_drive_backup_job(job_id=job.pk, user_id=other.pk)


@pytest.mark.django_db
def test_list_google_drive_backup_jobs_invalid_status_raises(tmp_path):
    root = tmp_path / "lib"
    root.mkdir()
    u = User.objects.create_user(username="gd_u14", password="pw")
    with pytest.raises(ValueError, match="Invalid status filter"):
        list_google_drive_backup_jobs(
            manga_root=str(root),
            series_id=1,
            user_id=u.pk,
            status="bogus",
        )
