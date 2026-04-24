from ninja import Router

from .schemas import GetJokeRequest, GetJokeResponse
from .services import random_joke

router = Router(tags=["Fun"])


@router.post("/v1.Fun.GetJoke", response=GetJokeResponse)
def get_joke(request, payload: GetJokeRequest):
    return GetJokeResponse(joke=random_joke())
