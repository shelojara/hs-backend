"""Async CBZ convert jobs (groceries Search pattern: django-q2 + row status)."""

from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from manga.models import CbzConvertJob, CbzConvertJobStatus, Series, SeriesItem
from manga.services import (
    create_cbz_convert_job,
    get_cbz_convert_job,
    list_cbz_convert_jobs,
    run_cbz_convert_job,
)

User = get_user_model()


@pytest.mark.django_db
@patch("manga.services.async_task")
def test_create_cbz_convert_job_persists_pending_and_enqueues_worker(mock_async, tmp_path):
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
    u = User.objects.create_user(username="u1", password="pw")

    jid = create_cbz_convert_job(
        manga_root=str(root),
        item_id=row.pk,
        kind="manga",
        user_id=u.pk,
    )
    job = CbzConvertJob.objects.get(pk=jid)
    assert job.user_id == u.pk
    assert job.manga_root == abs_root
    assert job.series_item_id == row.pk
    assert job.kind == "manga"
    assert job.status == CbzConvertJobStatus.PENDING
    mock_async.assert_called_once_with(
        "manga.scheduled_tasks.run_cbz_convert_job",
        jid,
        task_name=f"manga_cbz_convert:{jid}",
    )


@pytest.mark.django_db
@patch("manga.services.convert_cbz")
def test_run_cbz_convert_job_marks_completed(mock_convert, tmp_path):
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
    u = User.objects.create_user(username="u2", password="pw")
    job = CbzConvertJob.objects.create(
        user=u,
        manga_root=abs_root,
        series_item_id=row.pk,
        kind="manga",
    )

    run_cbz_convert_job(job_id=job.pk)

    mock_convert.assert_called_once_with(
        manga_root=abs_root,
        item_id=row.pk,
        kind="manga",
    )
    job.refresh_from_db()
    assert job.status == CbzConvertJobStatus.COMPLETED
    assert job.completed_at is not None
    assert job.failure_message is None


@pytest.mark.django_db
@patch("manga.services.convert_cbz", side_effect=RuntimeError("boom"))
def test_run_cbz_convert_job_marks_failed_with_message(_mock_convert, tmp_path):
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
    u = User.objects.create_user(username="u3", password="pw")
    job = CbzConvertJob.objects.create(
        user=u,
        manga_root=abs_root,
        series_item_id=row.pk,
        kind="manhwa",
    )

    run_cbz_convert_job(job_id=job.pk)

    job.refresh_from_db()
    assert job.status == CbzConvertJobStatus.FAILED
    assert job.completed_at is not None
    assert job.failure_message == "boom"


@pytest.mark.django_db
@patch("manga.services.convert_cbz")
def test_run_cbz_convert_job_skips_soft_deleted(mock_convert, tmp_path):
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
    u = User.objects.create_user(username="u4", password="pw")
    job = CbzConvertJob.objects.create(
        user=u,
        manga_root=abs_root,
        series_item_id=row.pk,
        kind="manga",
    )
    job.deleted_at = timezone.now()
    job.save(update_fields=["deleted_at"])

    run_cbz_convert_job(job_id=job.pk)

    mock_convert.assert_not_called()


@pytest.mark.django_db
def test_get_cbz_convert_job_returns_row_for_owner(tmp_path):
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
    u = User.objects.create_user(username="u5", password="pw")
    job = CbzConvertJob.objects.create(
        user=u,
        manga_root=abs_root,
        series_item_id=row.pk,
        kind="manga",
    )
    got = get_cbz_convert_job(job_id=job.pk, user_id=u.pk)
    assert got.pk == job.pk


@pytest.mark.django_db
def test_get_cbz_convert_job_wrong_user_raises(tmp_path):
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
    u = User.objects.create_user(username="u6", password="pw")
    other = User.objects.create_user(username="u7", password="pw")
    job = CbzConvertJob.objects.create(
        user=u,
        manga_root=abs_root,
        series_item_id=row.pk,
        kind="manga",
    )
    with pytest.raises(CbzConvertJob.DoesNotExist):
        get_cbz_convert_job(job_id=job.pk, user_id=other.pk)


@pytest.mark.django_db
def test_list_cbz_convert_jobs_caps_at_ten_newest_first(tmp_path):
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
    u = User.objects.create_user(username="u9", password="pw")
    ids: list[int] = []
    for _ in range(12):
        j = CbzConvertJob.objects.create(
            user=u,
            manga_root=abs_root,
            series_item_id=row.pk,
            kind="manga",
        )
        ids.append(j.pk)
    rows = list_cbz_convert_jobs(user_id=u.pk)
    assert len(rows) == 10
    assert [r.pk for r in rows] == list(reversed(ids[-10:]))
