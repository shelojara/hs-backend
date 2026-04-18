from __future__ import annotations

import secrets
import time
from typing import Any

import bcrypt
import jwt
from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AbstractBaseUser
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.http import HttpRequest

from pagechecker.models import ApiKey

# Length of stored `key_prefix` (first N chars of full secret); must match bearer lookup.
API_KEY_PREFIX_LEN = 12


class InvalidLogin(Exception):
    """Username/password wrong or user inactive."""


class UsernameTaken(Exception):
    """Chosen username already exists."""


class InvalidRegistration(Exception):
    """Validation failed (e.g. password policy)."""

    def __init__(self, messages: list[str]) -> None:
        self.messages = messages


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


def register_user(request: HttpRequest, *, username: str, password: str) -> str:
    """Create user account; returns JWT access token (same shape as login)."""
    User = get_user_model()
    name = username.strip()
    if not name:
        raise InvalidRegistration(["Username is required."])
    if User.objects.filter(username=name).exists():
        raise UsernameTaken
    candidate = User(username=name)
    try:
        validate_password(password, user=candidate)
    except ValidationError as e:
        raise InvalidRegistration(list(e.messages)) from None
    try:
        user = User.objects.create_user(username=name, password=password)
    except IntegrityError:
        raise UsernameTaken from None
    return _encode_access_token(
        user_id=user.pk,
        username=user.get_username(),
    )


def create_personal_api_key(user: AbstractBaseUser) -> str:
    """Persist new API key for user; returns full secret once (never stored)."""
    for _ in range(8):
        raw = secrets.token_urlsafe(32)
        key_prefix = raw[:API_KEY_PREFIX_LEN]
        if ApiKey.objects.filter(key_prefix=key_prefix).exists():
            continue
        key_hash = bcrypt.hashpw(raw.encode(), bcrypt.gensalt()).decode("ascii")
        ApiKey.objects.create(
            user_id=user.pk,
            key_prefix=key_prefix,
            key_hash=key_hash,
        )
        return raw
    raise RuntimeError("Could not allocate unique API key prefix.")


def delete_personal_api_key(user: AbstractBaseUser, *, api_key_id: int) -> None:
    """Remove API key row owned by user; no-op if id missing or not owned."""
    ApiKey.objects.filter(pk=api_key_id, user_id=user.pk).delete()


def list_personal_api_keys(user: AbstractBaseUser) -> list[ApiKey]:
    """Return API key metadata for user (prefix + created_at; never full secret)."""
    return list(ApiKey.objects.filter(user_id=user.pk))
