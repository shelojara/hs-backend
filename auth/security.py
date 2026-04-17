from __future__ import annotations

import hashlib
import hmac

import jwt
from django.conf import settings
from django.contrib.auth import get_user_model
from django.http import HttpRequest
from ninja.errors import AuthenticationError
from ninja.security import HttpBearer

User = get_user_model()


def _hash_api_key_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


class JwtAccessBearer(HttpBearer):
    """Bearer: JWT from `Auth.Login`, or `prefix_secret` API key (see `pagechecker.ApiKey`)."""

    def __call__(self, request: HttpRequest) -> User:
        user = super().__call__(request)
        if user is None:
            raise AuthenticationError(401, "Authentication required.")
        return user

    def authenticate(self, request: HttpRequest, token: str) -> User | None:
        user = self._authenticate_jwt(token)
        if user is not None:
            return user
        return self._authenticate_api_key(token)

    def _authenticate_jwt(self, token: str) -> User | None:
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

    def _authenticate_api_key(self, token: str) -> User | None:
        from pagechecker.models import ApiKey

        prefix, sep, secret = token.partition("_")
        if not sep or not prefix or not secret:
            return None
        row = (
            ApiKey.objects.filter(key_prefix=prefix)
            .only("key_hash", "user_id")
            .first()
        )
        if row is None:
            return None
        digest = _hash_api_key_secret(secret)
        if not hmac.compare_digest(digest, row.key_hash):
            return None
        return (
            User.objects.filter(pk=row.user_id, is_active=True)
            .only("id", "username")
            .first()
        )


jwt_access_bearer = JwtAccessBearer()
