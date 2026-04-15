from __future__ import annotations

import jwt
from django.conf import settings
from django.contrib.auth import get_user_model
from django.http import HttpRequest
from ninja.security import HttpBearer

User = get_user_model()


class JwtAccessBearer(HttpBearer):
    """Bearer JWT from `Auth.Login`; must be active access token for existing user."""

    def authenticate(self, request: HttpRequest, token: str) -> User | None:
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


jwt_access_bearer = JwtAccessBearer()
