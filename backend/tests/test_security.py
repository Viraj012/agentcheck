from app.security import hash_ip


def test_hash_ip_is_stable_salted_and_not_the_ip() -> None:
    first = hash_ip("203.0.113.9", "salt-a")
    assert first == hash_ip("203.0.113.9", "salt-a")
    assert first != hash_ip("203.0.113.9", "salt-b")
    assert first != hash_ip("203.0.113.10", "salt-a")
    assert "203.0.113.9" not in first
    assert len(first) == 64
