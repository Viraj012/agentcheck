"""URL normalization and crawl scope. The normalized form is also the cache key."""

import posixpath
from urllib.parse import urlsplit, urlunsplit

ALLOWED_PORTS = {"http": 80, "https": 443}


class InvalidURLError(ValueError):
    """The URL is malformed or not something we are willing to fetch."""


def normalize_url(raw: str) -> str:
    """Return a canonical http(s) URL, or raise InvalidURLError."""
    try:
        parts = urlsplit(raw.strip())
        port = parts.port
    except ValueError as exc:
        raise InvalidURLError(f"malformed URL: {raw!r}") from exc
    scheme = parts.scheme.lower()
    if scheme not in ALLOWED_PORTS:
        raise InvalidURLError("only http and https URLs are allowed")
    if parts.username is not None or parts.password is not None:
        raise InvalidURLError("URLs with credentials are not allowed")
    if port is not None and port != ALLOWED_PORTS[scheme]:
        raise InvalidURLError("only the default ports 80 and 443 are allowed")
    host = _canonical_host(parts.hostname)
    return urlunsplit((scheme, host, parts.path or "/", parts.query, ""))


def crawl_scope(start_url: str) -> str:
    """The path prefix a crawl stays inside: the directory of the start page."""
    path = urlsplit(start_url).path or "/"
    return path if path.endswith("/") else posixpath.dirname(path).rstrip("/") + "/"


def in_scope(url: str, start_url: str) -> bool:
    candidate, start = urlsplit(url), urlsplit(start_url)
    same_origin = (candidate.scheme, candidate.netloc) == (start.scheme, start.netloc)
    return same_origin and (candidate.path or "/").startswith(crawl_scope(start_url))


def _canonical_host(hostname: str | None) -> str:
    if not hostname:
        raise InvalidURLError("URL has no host")
    if ":" in hostname:
        return f"[{hostname}]"
    try:
        return hostname.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise InvalidURLError(f"invalid host name: {hostname!r}") from exc
