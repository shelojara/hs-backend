from ninja import Router

from auth.security import protected_api_auth
from markdown import services
from markdown.schemas import PingRequest, PingResponse

router = Router(auth=protected_api_auth, tags=["Markdown"])


@router.post("/v1.Markdown.Ping", response=PingResponse)
def ping(request, payload: PingRequest):
    _ = (request.auth, payload)
    return PingResponse(status=services.ping())
