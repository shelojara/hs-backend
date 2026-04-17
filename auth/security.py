from __future__ import annotations

import bcrypt
import jwt
from django.conf import settings
from django.contrib.auth import get_user_model
from django.http import HttpRequest
from ninja.errors import AuthenticationError
from ninja.security import HttpBearer

User = get_user_model()


class BearerOrApiKeyAuth(HttpBearer):
    """JWT access token or personal API key (Bearer body or ``X-API-Key`` header)."""

    def __call__(self, request: HttpRequest) -> User:
        user = super().__call__(request)
        if user is None:
            api_key_header = request.headers.get("X-API-Key")
            if api_key_header:
                token = api_key_header.strip()
                if token:
                    user = self.authenticate(request, token)
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
        from auth.services import API_KEY_PREFIX_LEN
        from pagechecker.models import ApiKey

        if len(token) < API_KEY_PREFIX_LEN:
            return None
        prefix = token[:API_KEY_PREFIX_LEN]
        row = (
            ApiKey.objects.filter(key_prefix=prefix)
            .only("key_hash", "user_id")
            .first()
        )
        if row is None:
            return None
        try:
            ok = bcrypt.checkpw(
                token.encode("utf-8"),
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


bearer_or_api_key_auth = BearerOrApiKeyAuth()
