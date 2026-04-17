"""create_personal_api_key persists prefix + hash; returns raw secret once."""

import bcrypt
import pytest
from django.contrib.auth import get_user_model

from auth.services import create_personal_api_key
from pagechecker.models import ApiKey

User = get_user_model()


@pytest.mark.django_db
def test_create_personal_api_key_stores_prefix_and_hash_not_plaintext():
    user = User.objects.create_user(username="key_owner", password="pw")
    raw = create_personal_api_key(user)

    assert len(raw) > 20
    row = ApiKey.objects.get(user=user)
    assert row.key_prefix == raw[:12]
    assert bcrypt.checkpw(raw.encode(), row.key_hash.encode("ascii"))
    assert raw not in row.key_hash
