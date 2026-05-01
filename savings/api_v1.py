from ninja import Router

from auth.security import protected_api_auth
from savings.schemas import PingSavingsRequest, PingSavingsResponse

router = Router(auth=protected_api_auth, tags=["Savings"])


@router.post("/v1.Savings.Ping", response=PingSavingsResponse)
def ping_savings(request, payload: PingSavingsRequest) -> PingSavingsResponse:
    _ = request.auth
    return PingSavingsResponse()
