import json

import jwt
import pytest
from django.conf import settings
from django.contrib.auth.models import User
from django.test import Client


@pytest.mark.django_db
def test_login_returns_jwt_for_valid_credentials():
    User.objects.create_user(username="alice", password="secret123")
    client = Client()
    res = client.post(
        "/api/v1.Auth.Login",
        data=json.dumps({"username": "alice", "password": "secret123"}),
        content_type="application/json",
    )
    assert res.status_code == 200
    body = res.json()
    assert body["token_type"] == "Bearer"
    token = body["access_token"]
    decoded = jwt.decode(
        token,
        settings.JWT_SIGNING_KEY,
        algorithms=[settings.JWT_ALGORITHM],
    )
    assert decoded["sub"] is not None
    assert decoded["username"] == "alice"
    assert decoded["token_type"] == "access"


@pytest.mark.django_db
def test_login_401_for_bad_password():
    User.objects.create_user(username="bob", password="right")
    client = Client()
    res = client.post(
        "/api/v1.Auth.Login",
        data=json.dumps({"username": "bob", "password": "wrong"}),
        content_type="application/json",
    )
    assert res.status_code == 401
