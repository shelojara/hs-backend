from savings import services


def test_ping() -> None:
    assert services.ping() == {"ok": True}
