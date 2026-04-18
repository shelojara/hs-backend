"""Tests for auth.services."""

import pytest
from django.contrib.auth import get_user_model

from auth.services import create_personal_api_key, delete_user_account
from pagechecker.models import ApiKey, Page, Question, Snapshot

User = get_user_model()


@pytest.mark.django_db
def test_delete_user_account_removes_user_and_owned_data():
    user = User.objects.create_user(username="gone", password="pw")
    other = User.objects.create_user(username="stay", password="pw")
    create_personal_api_key(user)
    q = Question.objects.create(owner=user, text="q?")
    page = Page.objects.create(owner=user, url="https://example.com/p")
    page.questions.add(q)
    Snapshot.objects.create(page=page, html_content="x", md_content="y")
    other_page = Page.objects.create(owner=other, url="https://example.com/o")

    delete_user_account(user)

    assert not User.objects.filter(pk=user.pk).exists()
    assert not Page.objects.filter(pk=page.pk).exists()
    assert not Question.objects.filter(pk=q.pk).exists()
    assert not ApiKey.objects.filter(user_id=user.pk).exists()
    assert User.objects.filter(pk=other.pk).exists()
    assert Page.objects.filter(pk=other_page.pk).exists()
