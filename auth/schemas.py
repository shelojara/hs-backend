from datetime import datetime

from ninja import Schema


class LoginRequest(Schema):
    username: str
    password: str


class RegisterRequest(Schema):
    username: str
    email: str
    password: str


class LoginResponse(Schema):
    access_token: str
    token_type: str = "Bearer"


class CreatePersonalApiKeyResponse(Schema):
    api_key: str


class DeletePersonalApiKeyRequest(Schema):
    api_key_id: int


class DeletePersonalApiKeyResponse(Schema):
    pass


class PersonalApiKey(Schema):
    id: int
    key_prefix: str
    created_at: datetime


class ListPersonalApiKeysResponse(Schema):
    api_keys: list[PersonalApiKey]


class DeleteUserResponse(Schema):
    pass
