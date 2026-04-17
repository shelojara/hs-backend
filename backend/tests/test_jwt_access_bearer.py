"""JwtAccessBearer enforces Bearer token and returns a User."""

import hashlib
import time

import jwt
import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import RequestFactory
from ninja.errors import AuthenticationError

from auth.security import jwt_access_bearer
from pagechecker.models import ApiKey

User = get_user_model()


def _access_token(*, user_id: int, username: str) -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "sub": str(user_id),
            "username": username,
            "iat": now,
            "exp": now + 3600,
            "token_type": "access",
        },
        settings.JWT_SIGNING_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )


@pytest.mark.django_db
def test_jwt_access_bearer_returns_user():
    user = User.objects.create_user(username="jwt_ok", password="pw")
    token = _access_token(user_id=user.pk, username=user.username)
    request = RequestFactory().post(
        "/api/x",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert jwt_access_bearer(request).pk == user.pk


@pytest.mark.django_db
def test_jwt_access_bearer_raises_when_no_header():
    request = RequestFactory().post("/api/x")
    with pytest.raises(AuthenticationError):
        jwt_access_bearer(request)


@pytest.mark.django_db
def test_jwt_access_bearer_raises_when_invalid_token():
    request = RequestFactory().post(
        "/api/x",
        HTTP_AUTHORIZATION="Bearer not-a-jwt",
    )
    with pytest.raises(AuthenticationError):
        jwt_access_bearer(request)


def _sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


@pytest.mark.django_db
def test_jwt_access_bearer_accepts_api_key():
    user = User.objects.create_user(username="key_ok", password="pw")
    prefix, secret = "pktest", "s3cr3t_value"
    ApiKey.objects.create(
        user=user,
        key_prefix=prefix,
        key_hash=_sha256_hex(secret),
    )
    token = f"{prefix}_{secret}"
    request = RequestFactory().post(
        "/api/x",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert jwt_access_bearer(request).pk == user.pk


@pytest.mark.django_db
def test_jwt_access_bearer_rejects_wrong_api_key_secret():
    user = User.objects.create_user(username="key_bad", password="pw")
    ApiKey.objects.create(
        user=user,
        key_prefix="pkbad",
        key_hash=_sha256_hex("correct"),
    )
    request = RequestFactory().post(
        "/api/x",
        HTTP_AUTHORIZATION="Bearer pkbad_wrong",
    )
    with pytest.raises(AuthenticationError):
        jwt_access_bearer(request)
