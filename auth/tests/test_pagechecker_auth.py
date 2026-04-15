import json

import jwt
import pytest
from django.conf import settings
from django.contrib.auth.models import User
from django.test import Client


@pytest.mark.django_db
def test_pagechecker_requires_bearer_token():
    client = Client()
    res = client.post(
        "/api/v1.PageChecker.ListPages",
        data=json.dumps({}),
        content_type="application/json",
    )
    assert res.status_code == 401


@pytest.mark.django_db
def test_pagechecker_rejects_invalid_bearer_token():
    client = Client()
    res = client.post(
        "/api/v1.PageChecker.ListPages",
        data=json.dumps({}),
        content_type="application/json",
        HTTP_AUTHORIZATION="Bearer not-a-jwt",
    )
    assert res.status_code == 401


@pytest.mark.django_db
def test_pagechecker_accepts_login_access_token():
    User.objects.create_user(username="carol", password="pw123456")
    client = Client()
    login_res = client.post(
        "/api/v1.Auth.Login",
        data=json.dumps({"username": "carol", "password": "pw123456"}),
        content_type="application/json",
    )
    assert login_res.status_code == 200
    token = login_res.json()["access_token"]

    pages_res = client.post(
        "/api/v1.PageChecker.ListPages",
        data=json.dumps({}),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert pages_res.status_code == 200
    assert pages_res.json() == {"pages": []}


@pytest.mark.django_db
def test_pagechecker_rejects_wrong_token_type_claim():
    user = User.objects.create_user(username="dave", password="pw123456")
    bad = jwt.encode(
        {
            "sub": str(user.pk),
            "username": user.get_username(),
            "token_type": "refresh",
            "exp": 9_999_999_999,
        },
        settings.JWT_SIGNING_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )
    client = Client()
    res = client.post(
        "/api/v1.PageChecker.ListPages",
        data=json.dumps({}),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {bad}",
    )
    assert res.status_code == 401


@pytest.mark.django_db
def test_pagechecker_rejects_inactive_user_token():
    user = User.objects.create_user(username="erin", password="pw123456")
    user.is_active = False
    user.save(update_fields=["is_active"])
    token = jwt.encode(
        {
            "sub": str(user.pk),
            "username": user.get_username(),
            "token_type": "access",
            "exp": 9_999_999_999,
        },
        settings.JWT_SIGNING_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )
    client = Client()
    res = client.post(
        "/api/v1.PageChecker.ListPages",
        data=json.dumps({}),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert res.status_code == 401
