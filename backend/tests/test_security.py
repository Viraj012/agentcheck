import httpx2
import pytest
from pydantic import ValidationError

from app.config import TURNSTILE_TEST_SECRET, Settings
from app.security import SITEVERIFY_URL, hash_ip, verify_turnstile


def test_hash_ip_is_stable_salted_and_not_the_ip() -> None:
    first = hash_ip("203.0.113.9", "salt-a")
    assert first == hash_ip("203.0.113.9", "salt-a")
    assert first != hash_ip("203.0.113.9", "salt-b")
    assert first != hash_ip("203.0.113.10", "salt-a")
    assert "203.0.113.9" not in first
    assert len(first) == 64


def cloudflare(success: bool, seen: list[dict] | None = None) -> httpx2.AsyncClient:
    def handle(request: httpx2.Request) -> httpx2.Response:
        assert str(request.url) == SITEVERIFY_URL
        if seen is not None:
            seen.append(request.read().decode())
        return httpx2.Response(200, json={"success": success})

    return httpx2.AsyncClient(transport=httpx2.MockTransport(handle))


async def test_turnstile_passes_when_cloudflare_says_success() -> None:
    seen: list = []
    assert await verify_turnstile("tok", "1.2.3.4", secret="s3", client=cloudflare(True, seen))
    sent = seen[0].replace(" ", "")
    assert '"response":"tok"' in sent and '"remoteip":"1.2.3.4"' in sent


async def test_turnstile_fails_when_cloudflare_says_no() -> None:
    assert not await verify_turnstile("tok", "ip", secret="s", client=cloudflare(False))


@pytest.mark.parametrize("token", [None, "", "x" * 2049])
async def test_missing_or_oversized_token_fails_without_calling_cloudflare(token) -> None:
    seen: list = []
    assert not await verify_turnstile(token, "ip", secret="s", client=cloudflare(True, seen))
    assert seen == []


async def test_network_error_fails_closed() -> None:
    def boom(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("down", request=request)

    client = httpx2.AsyncClient(transport=httpx2.MockTransport(boom))
    assert not await verify_turnstile("tok", "ip", secret="s", client=client)


def test_development_falls_back_to_cloudflare_test_secret() -> None:
    assert Settings(_env_file=None).turnstile_secret() == TURNSTILE_TEST_SECRET


@pytest.mark.parametrize(
    "overrides",
    [
        {},
        {"turnstile_secret_key": TURNSTILE_TEST_SECRET, "ip_hash_salt": "real-salt"},
        {"turnstile_secret_key": "real-secret"},
    ],
)
def test_production_requires_real_secrets(overrides: dict) -> None:
    with pytest.raises(ValidationError, match="production needs"):
        Settings(_env_file=None, environment="production", **overrides)


def test_production_with_real_secrets_is_valid() -> None:
    s = Settings(
        _env_file=None, environment="production", turnstile_secret_key="real", ip_hash_salt="salt"
    )
    assert s.turnstile_secret() == "real"
