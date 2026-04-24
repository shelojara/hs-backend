from ninja import Schema


class GetJokeRequest(Schema):
    pass


class GetJokeResponse(Schema):
    joke: str
