from django.contrib.auth import authenticate
from django.http import HttpRequest

from .jwt_tokens import encode_access_token


class InvalidLogin(Exception):
    """Username/password wrong or user inactive."""


def login(request: HttpRequest, *, username: str, password: str) -> str:
    user = authenticate(
        request,
        username=username,
        password=password,
    )
    if user is None or not user.is_active:
        raise InvalidLogin
    return encode_access_token(
        user_id=user.pk,
        username=user.get_username(),
    )
