from django.contrib.auth import authenticate
from ninja import Router
from ninja.errors import HttpError

from .jwt_tokens import encode_access_token
from .schemas import LoginRequest, LoginResponse

router = Router()


@router.post("/v1.Auth.Login", response=LoginResponse)
def login(request, payload: LoginRequest):
    user = authenticate(
        request,
        username=payload.username,
        password=payload.password,
    )
    if user is None or not user.is_active:
        raise HttpError(401, "Invalid username or password.")
    access_token = encode_access_token(
        user_id=user.pk,
        username=user.get_username(),
    )
    return LoginResponse(access_token=access_token)
