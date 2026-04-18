"""register_user creates account and returns JWT like login."""

import jwt
import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import RequestFactory

from auth.services import (
    EmailTaken,
    InvalidRegistration,
    UsernameTaken,
    register_user,
)

User = get_user_model()


@pytest.fixture
def http_request():
    return RequestFactory().post("/api/v1.Auth.Register")


@pytest.mark.django_db
def test_register_user_creates_user_and_returns_valid_access_token(http_request):
    token = register_user(
        http_request,
        username="new_user",
        email="new_user@example.com",
        password="valid-pass-1",
    )
    user = User.objects.get(username="new_user")
    assert user.email == "new_user@example.com"
    assert user.is_active
    payload = jwt.decode(
        token,
        settings.JWT_SIGNING_KEY,
        algorithms=[settings.JWT_ALGORITHM],
    )
    assert payload["sub"] == str(user.pk)
    assert payload["username"] == "new_user"
    assert payload["token_type"] == "access"


@pytest.mark.django_db
def test_register_user_rejects_duplicate_username(http_request):
    User.objects.create_user(username="taken", password="valid-pass-1")
    with pytest.raises(UsernameTaken):
        register_user(
            http_request,
            username="taken",
            email="other@example.com",
            password="other-valid-2",
        )


@pytest.mark.django_db
def test_register_user_rejects_blank_username(http_request):
    with pytest.raises(InvalidRegistration) as exc:
        register_user(
            http_request,
            username="   ",
            email="x@example.com",
            password="valid-pass-1",
        )
    assert "required" in exc.value.messages[0].lower()


@pytest.mark.django_db
def test_register_user_rejects_password_validation_failure(http_request):
    with pytest.raises(InvalidRegistration):
        register_user(
            http_request,
            username="u1",
            email="u1@example.com",
            password="short",
        )


@pytest.mark.django_db
def test_register_user_rejects_blank_email(http_request):
    with pytest.raises(InvalidRegistration) as exc:
        register_user(
            http_request,
            username="u2",
            email="   ",
            password="valid-pass-1",
        )
    assert "email" in exc.value.messages[0].lower()


@pytest.mark.django_db
def test_register_user_rejects_invalid_email(http_request):
    with pytest.raises(InvalidRegistration):
        register_user(
            http_request,
            username="u3",
            email="not-an-email",
            password="valid-pass-1",
        )


@pytest.mark.django_db
def test_register_user_rejects_duplicate_email_case_insensitive(http_request):
    User.objects.create_user(
        username="first",
        email="Same@Example.com",
        password="valid-pass-1",
    )
    with pytest.raises(EmailTaken):
        register_user(
            http_request,
            username="second",
            email="same@example.com",
            password="valid-pass-2",
        )
