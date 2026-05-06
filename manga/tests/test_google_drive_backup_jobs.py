"""Async Google Drive backup jobs (django-q2 + row status)."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model

from manga.models import GoogleDriveBackupJob, GoogleDriveBackupJobStatus, MangaLibrary, Series, SeriesItem
from manga.services import (
    create_google_drive_backup_job,
    get_google_drive_backup_job,
    list_google_drive_backup_jobs,
    run_google_drive_backup_job,
)

User = get_user_model()


def _lib_series(tmp_path) -> tuple[MangaLibrary, Series, str]:
    root = tmp_path / "lib"
    root.mkdir()
    abs_root = str(root.resolve())
    lib = MangaLibrary.objects.create(name="lib", filesystem_path=abs_root)
    s = Series.objects.create(library=lib, library_root=abs_root, series_rel_path="s", name="s")
    return lib, s, abs_root


@pytest.mark.django_db
@patch("manga.services.async_task")
def test_create_google_drive_backup_job_persists_pending_and_enqueues(mock_async, tmp_path):
    lib, s, abs_root = _lib_series(tmp_path)
    row_a = SeriesItem.objects.create(
        series=s,
        rel_path="s/a.cbz",
        filename="a.cbz",
        size_bytes=1,
    )
    row_b = SeriesItem.objects.create(
        series=s,
        rel_path="s/b.cbz",
        filename="b.cbz",
        size_bytes=1,
    )
    u = User.objects.create_user(username="gd_u1", password="pw")

    jids = create_google_drive_backup_job(
        library_id=lib.pk,
        series_id=s.pk,
        user_id=u.pk,
    )
    assert len(jids) == 2
    jobs = {GoogleDriveBackupJob.objects.get(pk=j) for j in jids}
    assert {j.series_item_id for j in jobs} == {row_a.pk, row_b.pk}
    for job in jobs:
        assert job.user_id == u.pk
        assert job.library_id == lib.pk
        assert job.manga_root == abs_root
        assert job.series_id == s.pk
        assert job.status == GoogleDriveBackupJobStatus.PENDING
    assert mock_async.call_count == 2
    for jid in jids:
        mock_async.assert_any_call(
            "manga.scheduled_tasks.run_google_drive_backup_job",
            jid,
            task_name=f"manga_gdrive_backup:{jid}",
        )


@pytest.mark.django_db
def test_create_google_drive_backup_job_empty_series_raises(tmp_path):
    lib, s, _ = _lib_series(tmp_path)
    u = User.objects.create_user(username="gd_u_empty", password="pw")
    with pytest.raises(ValueError, match="Series has no items"):
        create_google_drive_backup_job(
            library_id=lib.pk,
            series_id=s.pk,
            user_id=u.pk,
        )


@pytest.mark.django_db
@patch("manga.services.upload_file_to_folder", return_value="file_xyz")
@patch("manga.services.find_existing_file_id_with_same_size", return_value=None)
@patch("manga.services.ensure_series_drive_folder", return_value="folder_abc")
@patch("manga.services.resolve_cbz_download")
def test_run_google_drive_backup_job_success(
    mock_resolve,
    _mock_folder,
    _mock_find_existing,
    mock_upload,
    tmp_path,
):
    lib, s, abs_root = _lib_series(tmp_path)
    root = tmp_path / "lib"
    cbz = root / "s" / "ch.cbz"
    cbz.parent.mkdir()
    cbz.write_bytes(b"PK\x03\x04fake")
    row = SeriesItem.objects.create(
        series=s,
        rel_path="s/ch.cbz",
        filename="ch.cbz",
        size_bytes=1,
    )
    u = User.objects.create_user(username="gd_u2", password="pw")
    job = GoogleDriveBackupJob.objects.create(
        user=u,
        library_id=lib.pk,
        manga_root=abs_root,
        series=s,
        series_item_id=row.pk,
    )
    mock_resolve.return_value = SimpleNamespace(absolute_path=str(cbz), filename="ch.cbz")

    run_google_drive_backup_job(job_id=job.pk)

    job.refresh_from_db()
    assert job.status == GoogleDriveBackupJobStatus.COMPLETED, (job.status, job.failure_message)
    mock_resolve.assert_called_once_with(library_id=lib.pk, item_id=row.pk)
    assert job.completed_at is not None
    assert job.failure_message is None
    assert job.google_drive_file_id == "file_xyz"
    row.refresh_from_db()
    assert row.is_backed_up is True


@pytest.mark.django_db
@patch("manga.services.upload_file_to_folder")
@patch(
    "manga.services.find_existing_file_id_with_same_size",
    return_value="already_there",
)
@patch("manga.services.ensure_series_drive_folder", return_value="folder_abc")
@patch("manga.services.resolve_cbz_download")
def test_run_google_drive_backup_job_skips_upload_when_same_name_and_size(
    mock_resolve,
    _mock_folder,
    _mock_find_existing,
    mock_upload,
    tmp_path,
):
    lib, s, abs_root = _lib_series(tmp_path)
    root = tmp_path / "lib"
    cbz = root / "s" / "ch.cbz"
    cbz.parent.mkdir()
    cbz.write_bytes(b"PK\x03\x04fake")
    row = SeriesItem.objects.create(
        series=s,
        rel_path="s/ch.cbz",
        filename="ch.cbz",
        size_bytes=1,
    )
    u = User.objects.create_user(username="gd_u_skip", password="pw")
    job = GoogleDriveBackupJob.objects.create(
        user=u,
        library_id=lib.pk,
        manga_root=abs_root,
        series=s,
        series_item_id=row.pk,
    )
    mock_resolve.return_value = SimpleNamespace(absolute_path=str(cbz), filename="ch.cbz")

    run_google_drive_backup_job(job_id=job.pk)

    job.refresh_from_db()
    assert job.status == GoogleDriveBackupJobStatus.COMPLETED
    mock_upload.assert_not_called()
    assert job.google_drive_file_id == "already_there"
    row.refresh_from_db()
    assert row.is_backed_up is True


@pytest.mark.django_db
@patch("manga.services.resolve_cbz_download", side_effect=RuntimeError("boom"))
def test_run_google_drive_backup_job_marks_failed(_mock_resolve, tmp_path):
    lib, s, abs_root = _lib_series(tmp_path)
    row = SeriesItem.objects.create(
        series=s,
        rel_path="s/ch.cbz",
        filename="ch.cbz",
        size_bytes=1,
    )
    u = User.objects.create_user(username="gd_u3", password="pw")
    job = GoogleDriveBackupJob.objects.create(
        user=u,
        library_id=lib.pk,
        manga_root=abs_root,
        series=s,
        series_item_id=row.pk,
    )

    run_google_drive_backup_job(job_id=job.pk)

    job.refresh_from_db()
    assert job.status == GoogleDriveBackupJobStatus.FAILED
    assert job.completed_at is not None
    assert job.failure_message == "boom"
    row.refresh_from_db()
    assert row.is_backed_up is False


@pytest.mark.django_db
def test_get_google_drive_backup_job_owner(tmp_path):
    lib, s, abs_root = _lib_series(tmp_path)
    row = SeriesItem.objects.create(
        series=s,
        rel_path="s/ch.cbz",
        filename="ch.cbz",
        size_bytes=1,
    )
    u = User.objects.create_user(username="gd_u5", password="pw")
    job = GoogleDriveBackupJob.objects.create(
        user=u,
        library_id=lib.pk,
        manga_root=abs_root,
        series=s,
        series_item_id=row.pk,
    )
    got = get_google_drive_backup_job(job_id=job.pk, user_id=u.pk)
    assert got.pk == job.pk


@pytest.mark.django_db
def test_get_google_drive_backup_job_wrong_user_raises(tmp_path):
    lib, s, abs_root = _lib_series(tmp_path)
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
        library_id=lib.pk,
        manga_root=abs_root,
        series=s,
        series_item_id=row.pk,
    )
    with pytest.raises(GoogleDriveBackupJob.DoesNotExist):
        get_google_drive_backup_job(job_id=job.pk, user_id=other.pk)


@pytest.mark.django_db
def test_list_google_drive_backup_jobs_invalid_status_raises(tmp_path):
    lib, _, _ = _lib_series(tmp_path)
    u = User.objects.create_user(username="gd_u14", password="pw")
    with pytest.raises(ValueError, match="Invalid status filter"):
        list_google_drive_backup_jobs(
            library_id=lib.pk,
            series_id=1,
            user_id=u.pk,
            status="bogus",
        )
