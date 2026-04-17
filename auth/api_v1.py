from ninja import Router
from ninja.errors import HttpError

from auth.security import jwt_access_bearer

from .schemas import (
    CreatePersonalApiKeyResponse,
    DeletePersonalApiKeyRequest,
    DeletePersonalApiKeyResponse,
    LoginRequest,
    LoginResponse,
)
from .services import (
    InvalidLogin,
    create_personal_api_key,
    delete_personal_api_key,
    login as login_service,
)

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


@router.post(
    "/v1.Auth.CreatePersonalApiKey",
    response=CreatePersonalApiKeyResponse,
    auth=jwt_access_bearer,
)
def create_personal_api_key_endpoint(request):
    api_key = create_personal_api_key(request.auth)
    return CreatePersonalApiKeyResponse(api_key=api_key)


@router.post(
    "/v1.Auth.DeletePersonalApiKey",
    response=DeletePersonalApiKeyResponse,
    auth=jwt_access_bearer,
)
def delete_personal_api_key_endpoint(request, payload: DeletePersonalApiKeyRequest):
    delete_personal_api_key(request.auth, api_key_id=payload.api_key_id)
    return DeletePersonalApiKeyResponse()
