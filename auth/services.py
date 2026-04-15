from __future__ import annotations

import time
from typing import Any

import jwt
from django.conf import settings
from django.contrib.auth import authenticate
from django.http import HttpRequest


class InvalidLogin(Exception):
    """Username/password wrong or user inactive."""


def _encode_access_token(*, user_id: int, username: str) -> str:
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


def login(request: HttpRequest, *, username: str, password: str) -> str:
    user = authenticate(
        request,
        username=username,
        password=password,
    )
    if user is None or not user.is_active:
        raise InvalidLogin
    return _encode_access_token(
        user_id=user.pk,
        username=user.get_username(),
    )
