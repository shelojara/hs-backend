"""JWT Bearer + X-API-Key authenticators (Ninja multiple auth list)."""

import time

import bcrypt
import jwt
import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import RequestFactory
from ninja.errors import AuthenticationError

from auth.security import (
    JwtAccessBearerAuth,
    PersonalApiKeyHeaderAuth,
    protected_api_auth,
)
from auth.services import API_KEY_PREFIX_LEN
from pagechecker.models import ApiKey

User = get_user_model()


def _run_protected_auth(request):
    """Same order as Django Ninja: first truthy result wins."""
    for callback in protected_api_auth:
        result = callback(request)
        if result:
            return result
    raise AuthenticationError()


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
def test_jwt_access_bearer_auth_accepts_valid_jwt():
    user = User.objects.create_user(username="jwt_ok", password="pw")
    token = _access_token(user_id=user.pk, username=user.username)
    request = RequestFactory().post(
        "/api/x",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert JwtAccessBearerAuth()(request).pk == user.pk


@pytest.mark.django_db
def test_jwt_access_bearer_auth_rejects_non_jwt_bearer_token():
    request = RequestFactory().post(
        "/api/x",
        HTTP_AUTHORIZATION="Bearer not-a-jwt",
    )
    assert JwtAccessBearerAuth()(request) is None


@pytest.mark.django_db
def test_personal_api_key_header_auth_accepts_x_api_key():
    user = User.objects.create_user(username="key_header_ok", password="pw")
    raw = "x" * 40
    key_prefix = raw[:API_KEY_PREFIX_LEN]
    key_hash = bcrypt.hashpw(raw.encode(), bcrypt.gensalt()).decode("ascii")
    ApiKey.objects.create(
        user=user,
        key_prefix=key_prefix,
        key_hash=key_hash,
    )
    request = RequestFactory().post(
        "/api/x",
        HTTP_X_API_KEY=raw,
    )
    assert PersonalApiKeyHeaderAuth()(request).pk == user.pk


@pytest.mark.django_db
def test_protected_api_auth_accepts_jwt():
    user = User.objects.create_user(username="chain_jwt", password="pw")
    token = _access_token(user_id=user.pk, username=user.username)
    request = RequestFactory().post(
        "/api/x",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert _run_protected_auth(request).pk == user.pk


@pytest.mark.django_db
def test_protected_api_auth_accepts_api_key_via_x_api_key_only():
    user = User.objects.create_user(username="chain_key", password="pw")
    raw = "x" * 40
    key_prefix = raw[:API_KEY_PREFIX_LEN]
    key_hash = bcrypt.hashpw(raw.encode(), bcrypt.gensalt()).decode("ascii")
    ApiKey.objects.create(
        user=user,
        key_prefix=key_prefix,
        key_hash=key_hash,
    )
    request = RequestFactory().post(
        "/api/x",
        HTTP_X_API_KEY=raw,
    )
    assert _run_protected_auth(request).pk == user.pk


@pytest.mark.django_db
def test_protected_api_auth_raises_when_no_credentials():
    request = RequestFactory().post("/api/x")
    with pytest.raises(AuthenticationError):
        _run_protected_auth(request)


@pytest.mark.django_db
def test_protected_api_auth_api_key_not_valid_in_authorization_bearer():
    """Personal API key must use X-API-Key; Bearer is JWT-only."""
    user = User.objects.create_user(username="key_bearer", password="pw")
    raw = "x" * 40
    ApiKey.objects.create(
        user=user,
        key_prefix=raw[:API_KEY_PREFIX_LEN],
        key_hash=bcrypt.hashpw(raw.encode(), bcrypt.gensalt()).decode("ascii"),
    )
    request = RequestFactory().post(
        "/api/x",
        HTTP_AUTHORIZATION=f"Bearer {raw}",
    )
    with pytest.raises(AuthenticationError):
        _run_protected_auth(request)


@pytest.mark.django_db
def test_protected_api_auth_rejects_wrong_api_key_secret():
    user = User.objects.create_user(username="key_bad", password="pw")
    raw = "y" * 40
    key_hash = bcrypt.hashpw(raw.encode(), bcrypt.gensalt()).decode("ascii")
    ApiKey.objects.create(
        user=user,
        key_prefix=raw[:API_KEY_PREFIX_LEN],
        key_hash=key_hash,
    )
    request = RequestFactory().post(
        "/api/x",
        HTTP_X_API_KEY="z" * 40,
    )
    with pytest.raises(AuthenticationError):
        _run_protected_auth(request)
