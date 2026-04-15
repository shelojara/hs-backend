from ninja import Router
from ninja.errors import HttpError

from .schemas import LoginRequest, LoginResponse
from .services import InvalidLogin, login as login_service

router = Router()


@router.post("/v1.Auth.Login", response=LoginResponse)
def login(request, payload: LoginRequest):
    try:
        access_token = login_service(
            request,
            username=payload.username,
            password=payload.password,
        )
    except InvalidLogin:
        raise HttpError(401, "Invalid username or password.") from None
    return LoginResponse(access_token=access_token)
