from ninja import Router
from ninja.errors import HttpError

from auth.security import protected_api_auth

from .schemas import (
    CreatePersonalApiKeyResponse,
    DeletePersonalApiKeyRequest,
    DeletePersonalApiKeyResponse,
    ListPersonalApiKeysResponse,
    LoginRequest,
    LoginResponse,
    PersonalApiKey,
    RegisterRequest,
)
from .services import (
    InvalidLogin,
    InvalidRegistration,
    UsernameTaken,
    create_personal_api_key,
    delete_personal_api_key,
    list_personal_api_keys,
    login as login_service,
    register_user,
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


@router.post("/v1.Auth.Register", response=LoginResponse)
def register(request, payload: RegisterRequest):
    try:
        access_token = register_user(
            request,
            username=payload.username,
            password=payload.password,
        )
    except UsernameTaken:
        raise HttpError(409, "Username already taken.") from None
    except InvalidRegistration as e:
        raise HttpError(400, "; ".join(e.messages)) from None
    return LoginResponse(access_token=access_token)


@router.post(
    "/v1.Auth.CreatePersonalApiKey",
    response=CreatePersonalApiKeyResponse,
    auth=protected_api_auth,
)
def create_personal_api_key_endpoint(request):
    api_key = create_personal_api_key(request.auth)
    return CreatePersonalApiKeyResponse(api_key=api_key)


@router.post(
    "/v1.Auth.DeletePersonalApiKey",
    response=DeletePersonalApiKeyResponse,
    auth=protected_api_auth,
)
def delete_personal_api_key_endpoint(request, payload: DeletePersonalApiKeyRequest):
    delete_personal_api_key(request.auth, api_key_id=payload.api_key_id)
    return DeletePersonalApiKeyResponse()


@router.post(
    "/v1.Auth.ListPersonalApiKeys",
    response=ListPersonalApiKeysResponse,
    auth=protected_api_auth,
)
def list_personal_api_keys_endpoint(request):
    rows = list_personal_api_keys(request.auth)
    return ListPersonalApiKeysResponse(
        api_keys=[
            PersonalApiKey(
                id=row.pk,
                key_prefix=row.key_prefix,
                created_at=row.created_at,
            )
            for row in rows
        ],
    )
