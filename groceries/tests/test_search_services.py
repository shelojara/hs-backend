"""Tests for async Gemini search (CreateSearch flow)."""

from decimal import Decimal
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from groceries.gemini_service import MerchantProductInfo, PreferredMerchantContext
from groceries.models import Merchant, Search, SearchStatus
from groceries.services import create_search, run_search_background

User = get_user_model()


def _user():
    return User.objects.create_user(username="searcher", password="pw")


@pytest.mark.django_db
def test_create_search_empty_query_raises():
    user = _user()
    with pytest.raises(ValueError, match="empty"):
        create_search(query="   ", user_id=user.pk)


@pytest.mark.django_db
@patch("groceries.scheduled_tasks.async_task")
def test_create_search_enqueues_and_returns_id(mock_async):
    user = _user()
    search_id = create_search(query="  milk  ", user_id=user.pk)
    row = Search.objects.get(pk=search_id)
    assert row.query == "milk"
    assert row.status == SearchStatus.PENDING
    mock_async.assert_called_once()
    assert mock_async.call_args[0][0] == "groceries.scheduled_tasks.run_search_job"
    assert mock_async.call_args[0][1] == search_id


@pytest.mark.django_db
@patch("groceries.services._gemini_search_candidate_dicts")
def test_run_search_background_completes(mock_candidates):
    mock_candidates.return_value = [{"display_name": "Leche"}]
    user = _user()
    s = Search.objects.create(user=user, query="leche", status=SearchStatus.PENDING)
    run_search_background(s.id)
    s.refresh_from_db()
    assert s.status == SearchStatus.COMPLETED
    assert s.result_candidates == [{"display_name": "Leche"}]
    assert s.completed_at is not None
    mock_candidates.assert_called_once_with(query="leche", user_id=user.pk)


@pytest.mark.django_db
@patch(
    "groceries.services._gemini_search_candidate_dicts",
    side_effect=ValueError("boom"),
)
def test_run_search_background_marks_failed(_mock_candidates):
    user = _user()
    s = Search.objects.create(user=user, query="q", status=SearchStatus.PENDING)
    before = timezone.now()
    run_search_background(s.id)
    s.refresh_from_db()
    assert s.status == SearchStatus.FAILED
    assert s.completed_at is not None
    assert s.completed_at >= before


@pytest.mark.django_db
@patch("groceries.services._gemini_search_candidate_dicts")
def test_run_search_background_skips_non_pending(mock_candidates):
    user = _user()
    s = Search.objects.create(
        user=user,
        query="q",
        status=SearchStatus.COMPLETED,
        result_candidates=[{"a": 1}],
        completed_at=timezone.now(),
    )
    run_search_background(s.id)
    mock_candidates.assert_not_called()


@pytest.mark.django_db
@patch("groceries.services.gemini_service.fetch_merchant_product_candidates")
def test_gemini_search_candidate_dicts_uses_preferred_merchants(mock_fetch):
    from groceries.services import _gemini_search_candidate_dicts

    mock_fetch.return_value = [
        MerchantProductInfo(
            display_name="Milk",
            standard_name="Leche",
            brand="",
            price=Decimal("1000"),
            format="1 L",
            emoji="🥛",
            merchant="Lider",
        ),
    ]
    user = _user()
    Merchant.objects.create(
        user=user,
        name="Jumbo",
        website="https://www.jumbo.cl",
        preference_order=0,
    )
    out = _gemini_search_candidate_dicts(query="milk", user_id=user.pk)
    assert out[0]["price"] == 1000
    pref = mock_fetch.call_args.kwargs["preferred_merchants"]
    assert pref == [
        PreferredMerchantContext(name="Jumbo", website="https://www.jumbo.cl"),
    ]
