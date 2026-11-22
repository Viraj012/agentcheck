"""Visitor identity without storing raw IP addresses, and the Turnstile bot check."""

import hashlib
import hmac

import httpx2
from starlette.requests import Request

from app.config import Settings

SITEVERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
TURNSTILE_TOKEN_MAX = 2048


def hash_ip(ip: str, salt: str) -> str:
    """Keyed SHA-256 of the IP. Stable for rate limits, not reversible without the salt."""
    return hmac.new(salt.encode(), ip.encode(), hashlib.sha256).hexdigest()


async def verify_turnstile(
    token: str | None, ip: str, *, secret: str, client: httpx2.AsyncClient
) -> bool:
    """Ask Cloudflare whether the widget token is valid. Any error counts as a failure."""
    if not token or len(token) > TURNSTILE_TOKEN_MAX:
        return False
    try:
        response = await client.post(
            SITEVERIFY_URL, json={"secret": secret, "response": token, "remoteip": ip}
        )
        body = response.json()
        return (
            response.status_code == 200 and isinstance(body, dict) and body.get("success") is True
        )
    except (httpx2.HTTPError, ValueError):
        return False


def client_ip(request: Request, settings: Settings) -> str:
    """The visitor's IP. Behind Render, Cloudflare sets CF-Connecting-IP to the real client;
    unlike the leftmost X-Forwarded-For entry, callers can't forge it."""
    if settings.client_ip_header:
        forwarded = request.headers.get(settings.client_ip_header.lower(), "").strip()
        if forwarded:
            return forwarded
    return request.client.host if request.client else "unknown"
