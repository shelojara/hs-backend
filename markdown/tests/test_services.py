from markdown import services


def test_ping_returns_ok():
    assert services.ping() == "ok"
