from ninja import Schema


class PingSavingsRequest(Schema):
    """Empty body for RPC transport consistency."""

    pass


class PingSavingsResponse(Schema):
    ok: bool = True
