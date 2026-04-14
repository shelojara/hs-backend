"""Encode short-lived JWT access tokens for API login."""

from __future__ import annotations

import time
from typing import Any

import jwt
from django.conf import settings


def encode_access_token(*, user_id: int, username: str) -> str:
    now = int(time.time())
    exp = now + int(settings.JWT_ACCESS_TOKEN_LIFETIME_SECONDS)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "username": username,
        "iat": now,
        "exp": exp,
        "token_type": "access",
    }
    return jwt.encode(
        payload,
        settings.JWT_SIGNING_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )
