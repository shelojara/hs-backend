from ninja import Schema


class PingRequest(Schema):
    """RPC payload placeholder; no fields yet."""


class PingResponse(Schema):
    status: str
