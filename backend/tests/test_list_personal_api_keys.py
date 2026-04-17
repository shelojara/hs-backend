"""list_personal_api_keys returns metadata for caller; no cross-user leakage."""

import pytest
from django.contrib.auth import get_user_model

from auth.services import create_personal_api_key, list_personal_api_keys
from pagechecker.models import ApiKey

User = get_user_model()


@pytest.mark.django_db
def test_list_personal_api_keys_returns_owned_rows_ordered_newest_first():
    user = User.objects.create_user(username="k1", password="pw")
    create_personal_api_key(user)
    create_personal_api_key(user)

    rows = list_personal_api_keys(user)
    assert len(rows) == 2
    assert rows[0].created_at >= rows[1].created_at
    assert {r.user_id for r in rows} == {user.pk}


@pytest.mark.django_db
def test_list_personal_api_keys_excludes_other_users_keys():
    owner = User.objects.create_user(username="own", password="pw")
    other = User.objects.create_user(username="oth", password="pw")
    create_personal_api_key(owner)
    create_personal_api_key(other)

    rows = list_personal_api_keys(owner)
    assert len(rows) == 1
    assert rows[0].user_id == owner.pk
    assert ApiKey.objects.count() == 2
