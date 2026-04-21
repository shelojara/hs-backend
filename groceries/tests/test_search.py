from decimal import Decimal
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from groceries.gemini_service import MerchantProductInfo
from groceries.models import Search, SearchStatus
from groceries.services import create_search, list_searches, run_product_search_job

User = get_user_model()


@pytest.mark.django_db
@patch("groceries.services.async_task")
def test_create_search_persists_pending_and_enqueues_worker(mock_async):
    u = User.objects.create_user(username="s1", password="pw")
    sid = create_search(query="  leche  ", user_id=u.pk)
    row = Search.objects.get(pk=sid)
    assert row.user_id == u.pk
    assert row.query == "leche"
    assert row.status == SearchStatus.PENDING
    assert row.result_candidates == []
    mock_async.assert_called_once_with(
        "groceries.scheduled_tasks.run_product_search_job",
        sid,
        task_name=f"groceries_product_search:{sid}",
    )


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_merchant_product_candidates",
    return_value=[
        MerchantProductInfo(
            display_name="Leche 1 L",
            standard_name="Leche entera",
            brand="Colún",
            price=Decimal("1990"),
            format="1 L",
            emoji="🥛",
            merchant="Lider",
        ),
    ],
)
def test_run_product_search_job_marks_completed_with_candidates(_mock_gemini):
    u = User.objects.create_user(username="s2", password="pw")
    row = Search.objects.create(user_id=u.pk, query="leche")
    run_product_search_job(search_id=row.pk)
    row.refresh_from_db()
    assert row.status == SearchStatus.COMPLETED
    assert row.completed_at is not None
    assert row.result_candidates == [
        {
            "display_name": "Leche 1 L",
            "standard_name": "Leche entera",
            "brand": "Colún",
            "price": "1990.00",
            "format": "1 L",
            "emoji": "🥛",
            "merchant": "Lider",
        },
    ]


@pytest.mark.django_db
@patch(
    "groceries.services.gemini_service.fetch_merchant_product_candidates",
    side_effect=RuntimeError("no key"),
)
def test_run_product_search_job_runtime_error_marks_failed(_mock_gemini):
    u = User.objects.create_user(username="s3", password="pw")
    row = Search.objects.create(user_id=u.pk, query="x")
    before = timezone.now()
    run_product_search_job(search_id=row.pk)
    row.refresh_from_db()
    assert row.status == SearchStatus.FAILED
    assert row.completed_at is not None
    assert row.completed_at >= before
    assert row.result_candidates == []


@pytest.mark.django_db
def test_list_searches_returns_latest_ten_newest_first_ordered_by_pk():
    u = User.objects.create_user(username="ls1", password="pw")
    other = User.objects.create_user(username="ls2", password="pw")
    ids = []
    for i in range(12):
        row = Search.objects.create(user_id=u.pk, query=f"q{i}")
        ids.append(row.pk)
    for i in range(3):
        Search.objects.create(user_id=other.pk, query=f"other{i}")
    rows = list_searches(user_id=u.pk)
    assert len(rows) == 10
    want = list(reversed(ids[-10:]))
    assert [r.pk for r in rows] == want
    assert all(r.user_id == u.pk for r in rows)
