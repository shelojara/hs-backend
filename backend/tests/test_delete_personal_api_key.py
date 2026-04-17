"""delete_personal_api_key removes row for owner only."""

import pytest
from django.contrib.auth import get_user_model

from auth.services import create_personal_api_key, delete_personal_api_key
from pagechecker.models import ApiKey

User = get_user_model()


@pytest.mark.django_db
def test_delete_personal_api_key_removes_owned_key():
    user = User.objects.create_user(username="owner", password="pw")
    raw = create_personal_api_key(user)
    key_id = ApiKey.objects.get(user=user).pk

    delete_personal_api_key(user, api_key_id=key_id)

    assert not ApiKey.objects.filter(pk=key_id).exists()
    assert raw  # secret was created; row gone


@pytest.mark.django_db
def test_delete_personal_api_key_other_user_unchanged():
    owner = User.objects.create_user(username="a", password="pw")
    other = User.objects.create_user(username="b", password="pw")
    create_personal_api_key(owner)
    create_personal_api_key(other)
    other_key_id = ApiKey.objects.get(user=other).pk

    delete_personal_api_key(owner, api_key_id=other_key_id)

    assert ApiKey.objects.filter(pk=other_key_id).exists()


@pytest.mark.django_db
def test_delete_personal_api_key_unknown_id_noop():
    user = User.objects.create_user(username="solo", password="pw")
    create_personal_api_key(user)

    delete_personal_api_key(user, api_key_id=999_999)

    assert ApiKey.objects.filter(user=user).count() == 1
