"""SSRF guard: decide whether a host is safe to connect to.

A host is allowed only if every address it resolves to is a public unicast address.
The fetcher then connects to one of exactly those checked addresses, so a second DNS
lookup (DNS rebinding) cannot swap in a private address after the check.
"""

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable

Resolver = Callable[[str], Awaitable[list[str]]]


class BlockedAddressError(Exception):
    """The host is private, reserved, unresolvable, or otherwise not allowed."""


async def system_resolver(host: str) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return [str(info[4][0]).split("%", 1)[0] for info in infos]


def is_public_ip(ip: str) -> bool:
    address = ipaddress.ip_address(ip)
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    return address.is_global and not address.is_multicast


async def resolve_public(host: str, resolver: Resolver) -> list[str]:
    """Return the host's addresses if all are public; otherwise raise BlockedAddressError."""
    bare = host.strip("[]")
    if _is_ip_literal(bare):
        addresses = [bare]
    else:
        try:
            addresses = await resolver(bare)
        except OSError as exc:
            raise BlockedAddressError(f"cannot resolve {bare}") from exc
    if not addresses:
        raise BlockedAddressError(f"{bare} has no addresses")
    for address in addresses:
        if not is_public_ip(address):
            raise BlockedAddressError(f"{bare} resolves to non-public address {address}")
    return addresses


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True
