from ninja import Schema


class LoginRequest(Schema):
    username: str
    password: str


class LoginResponse(Schema):
    access_token: str
    token_type: str = "Bearer"


class CreatePersonalApiKeyResponse(Schema):
    api_key: str
