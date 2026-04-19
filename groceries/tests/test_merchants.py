from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model

from groceries.models import Merchant
from groceries.services import (
    create_user_merchant,
    delete_user_merchant,
    list_user_merchants,
    update_user_merchant,
)

User = get_user_model()


def _user():
    return User.objects.create_user(username="m1", password="pw")


@pytest.mark.django_db
@patch(
    "groceries.services.fetch_favicon_url",
    return_value="https://example.com/favicon.ico",
)
def test_create_merchant_normalizes_website_and_stores_favicon(_mock_fav):
    u = _user()
    m = create_user_merchant(
        user_id=u.pk,
        name="  Acme  ",
        website="example.com",
    )
    assert m.name == "Acme"
    assert m.website == "https://example.com"
    assert m.favicon_url == "https://example.com/favicon.ico"


@pytest.mark.django_db
@patch("groceries.services.fetch_favicon_url", return_value="")
def test_list_merchants_ordered_by_preference_order(_mock_fav):
    u = _user()
    first = create_user_merchant(user_id=u.pk, name="Zed", website="https://z.com")
    second = create_user_merchant(user_id=u.pk, name="Alpha", website="https://a.com")
    rows = list_user_merchants(user_id=u.pk)
    assert [r.name for r in rows] == ["Zed", "Alpha"]
    assert first.preference_order == 0
    assert second.preference_order == 1


@pytest.mark.django_db
@patch("groceries.services.fetch_favicon_url", return_value="https://x/f.ico")
def test_update_merchant(_mock_fav):
    u = _user()
    m = create_user_merchant(user_id=u.pk, name="Old", website="https://old.com")
    updated = update_user_merchant(
        user_id=u.pk,
        merchant_id=m.pk,
        name="New",
        website="https://new.com",
    )
    assert updated.name == "New"
    assert updated.website == "https://new.com"
    assert updated.favicon_url == "https://x/f.ico"


@pytest.mark.django_db
@patch("groceries.services.fetch_favicon_url", return_value="")
def test_delete_merchant(_mock_fav):
    u = _user()
    m = create_user_merchant(user_id=u.pk, name="X", website="https://x.com")
    delete_user_merchant(user_id=u.pk, merchant_id=m.pk)
    assert not Merchant.objects.filter(pk=m.pk).exists()
