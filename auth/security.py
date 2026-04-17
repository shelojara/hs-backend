from __future__ import annotations

import bcrypt
import jwt
from django.conf import settings
from django.contrib.auth import get_user_model
from django.http import HttpRequest
from ninja.security import APIKeyHeader, HttpBearer

User = get_user_model()


def _authenticate_jwt_access(token: str) -> User | None:
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SIGNING_KEY,
            algorithms=[settings.JWT_ALGORITHM],
            options={"require": ["exp", "sub"]},
        )
    except jwt.PyJWTError:
        return None
    if payload.get("token_type") != "access":
        return None
    try:
        user_id = int(payload["sub"])
    except (TypeError, ValueError):
        return None
    return (
        User.objects.filter(pk=user_id, is_active=True)
        .only("id", "username")
        .first()
    )


def _authenticate_personal_api_key(secret: str) -> User | None:
    from auth.services import API_KEY_PREFIX_LEN
    from pagechecker.models import ApiKey

    if len(secret) < API_KEY_PREFIX_LEN:
        return None
    prefix = secret[:API_KEY_PREFIX_LEN]
    row = (
        ApiKey.objects.filter(key_prefix=prefix)
        .only("key_hash", "user_id")
        .first()
    )
    if row is None:
        return None
    try:
        ok = bcrypt.checkpw(
            secret.encode("utf-8"),
            row.key_hash.encode("ascii"),
        )
    except ValueError:
        return None
    if not ok:
        return None
    return (
        User.objects.filter(pk=row.user_id, is_active=True)
        .only("id", "username")
        .first()
    )


class JwtAccessBearerAuth(HttpBearer):
    """``Authorization: Bearer`` JWT access token from ``Auth.Login``."""

    def authenticate(self, request: HttpRequest, token: str) -> User | None:
        return _authenticate_jwt_access(token)


class PersonalApiKeyHeaderAuth(APIKeyHeader):
    """``X-API-Key`` personal API key from ``Auth.CreatePersonalApiKey``."""

    param_name = "X-API-Key"

    def authenticate(
        self, request: HttpRequest, key: str | None
    ) -> User | None:
        if not key:
            return None
        secret = key.strip()
        if not secret:
            return None
        return _authenticate_personal_api_key(secret)


# Django Ninja tries each authenticator in order until one returns a user.
# See: https://django-ninja.dev/guides/authentication/ — Multiple authenticators
protected_api_auth = [JwtAccessBearerAuth(), PersonalApiKeyHeaderAuth()]
