"""Tests for async Gemini search (CreateSearch flow)."""

from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from pagechecker.models import Search, SearchStatus
from pagechecker.services import create_search, run_search_background

User = get_user_model()


def _user():
    return User.objects.create_user(username="searcher", password="pw")


@pytest.mark.django_db
def test_create_search_empty_query_raises():
    user = _user()
    with pytest.raises(ValueError, match="empty"):
        create_search(query="   ", user_id=user.pk)


@pytest.mark.django_db
@patch("pagechecker.scheduled_tasks.async_task")
def test_create_search_enqueues_and_returns_id(mock_async):
    user = _user()
    search_id = create_search(query="  milk  ", user_id=user.pk)
    row = Search.objects.get(pk=search_id)
    assert row.query == "milk"
    assert row.status == SearchStatus.PENDING
    mock_async.assert_called_once()
    assert mock_async.call_args[0][0] == "pagechecker.scheduled_tasks.run_search_job"
    assert mock_async.call_args[0][1] == search_id


@pytest.mark.django_db
@patch(
    "pagechecker.services.gemini_service.search_with_google_grounding",
    return_value=[{"display_name": "Leche"}],
)
def test_run_search_background_completes(mock_search):
    user = _user()
    s = Search.objects.create(user=user, query="leche", status=SearchStatus.PENDING)
    run_search_background(s.id)
    s.refresh_from_db()
    assert s.status == SearchStatus.COMPLETED
    assert s.result_candidates == [{"display_name": "Leche"}]
    assert s.completed_at is not None
    mock_search.assert_called_once_with(query="leche")


@pytest.mark.django_db
@patch(
    "pagechecker.services.gemini_service.search_with_google_grounding",
    side_effect=RuntimeError("no key"),
)
def test_run_search_background_marks_failed(_mock_search):
    user = _user()
    s = Search.objects.create(user=user, query="q", status=SearchStatus.PENDING)
    before = timezone.now()
    run_search_background(s.id)
    s.refresh_from_db()
    assert s.status == SearchStatus.FAILED
    assert s.completed_at is not None
    assert s.completed_at >= before


@pytest.mark.django_db
@patch("pagechecker.services.gemini_service.search_with_google_grounding")
def test_run_search_background_skips_non_pending(mock_search):
    user = _user()
    s = Search.objects.create(
        user=user,
        query="q",
        status=SearchStatus.COMPLETED,
        result_candidates=[{"a": 1}],
        completed_at=timezone.now(),
    )
    run_search_background(s.id)
    mock_search.assert_not_called()
