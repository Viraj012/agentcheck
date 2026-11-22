import pytest

from app.crawler.ssrf import BlockedAddressError, is_public_ip, resolve_public, system_resolver
from tests.crawler.fakes import fake_resolver

PUBLIC = "93.184.216.34"

BLOCKED_IPS = [
    "127.0.0.1",
    "127.1.2.3",
    "0.0.0.0",
    "10.0.0.5",
    "172.16.0.1",
    "172.31.255.255",
    "192.168.1.1",
    "169.254.169.254",
    "100.64.0.1",
    "224.0.0.1",
    "255.255.255.255",
    "::1",
    "::",
    "fe80::1",
    "fc00::1",
    "fd12:3456::1",
    "ff02::1",
    "::ffff:127.0.0.1",
    "::ffff:169.254.169.254",
]


@pytest.mark.parametrize("ip", BLOCKED_IPS)
def test_non_public_ips_are_blocked(ip: str) -> None:
    assert not is_public_ip(ip)


@pytest.mark.parametrize("ip", [PUBLIC, "8.8.8.8", "2606:4700:4700::1111"])
def test_public_ips_are_allowed(ip: str) -> None:
    assert is_public_ip(ip)


@pytest.mark.parametrize("host", ["127.0.0.1", "10.1.2.3", "169.254.169.254", "[::1]", "::1"])
async def test_ip_literal_hosts_are_blocked_without_dns(host: str) -> None:
    with pytest.raises(BlockedAddressError):
        await resolve_public(host, fake_resolver({}))


async def test_localhost_is_blocked() -> None:
    resolver = fake_resolver({"localhost": ["127.0.0.1", "::1"]})
    with pytest.raises(BlockedAddressError):
        await resolve_public("localhost", resolver)


async def test_hostname_resolving_to_private_ip_is_blocked() -> None:
    resolver = fake_resolver({"intranet.example.com": ["10.0.0.7"]})
    with pytest.raises(BlockedAddressError, match="10.0.0.7"):
        await resolve_public("intranet.example.com", resolver)


async def test_any_private_record_blocks_the_host() -> None:
    resolver = fake_resolver({"mixed.example.com": [PUBLIC, "192.168.0.10"]})
    with pytest.raises(BlockedAddressError):
        await resolve_public("mixed.example.com", resolver)


async def test_unresolvable_host_is_blocked() -> None:
    with pytest.raises(BlockedAddressError, match="resolve"):
        await resolve_public("nope.example.com", fake_resolver({}))


async def test_public_host_returns_its_addresses() -> None:
    resolver = fake_resolver({"help.example.com": [PUBLIC]})
    assert await resolve_public("help.example.com", resolver) == [PUBLIC]


@pytest.mark.parametrize("host", ["localhost", "127.1", "2130706433", "0x7f000001"])
async def test_system_resolver_catches_disguised_loopback(host: str) -> None:
    with pytest.raises(BlockedAddressError):
        await resolve_public(host, system_resolver)
