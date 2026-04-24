from fun.services import JOKES_ES, random_joke


def test_random_joke_returns_member_of_pool():
    assert random_joke() in JOKES_ES
