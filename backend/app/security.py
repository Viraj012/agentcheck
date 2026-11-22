"""Visitor identity without storing raw IP addresses."""

import hashlib
import hmac


def hash_ip(ip: str, salt: str) -> str:
    """Keyed SHA-256 of the IP. Stable for rate limits, not reversible without the salt."""
    return hmac.new(salt.encode(), ip.encode(), hashlib.sha256).hexdigest()
