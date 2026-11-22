"""Serve a folder of static files to the crawler without a network, for tests and demos.

The SSRF guard still runs: `static_resolver` maps the site's host name to a public address,
the guard checks and pins it, and `static_site_transport` answers the pinned request from disk.
"""

from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path

import httpx2

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".xml": "application/xml",
    ".css": "text/css",
}


def static_resolver(mapping: Mapping[str, list[str]]) -> Callable[[str], Awaitable[list[str]]]:
    """Resolve names from a fixed table; unknown names fail like NXDOMAIN."""

    async def resolve(host: str) -> list[str]:
        if host not in mapping:
            raise OSError(f"cannot resolve {host}")
        return list(mapping[host])

    return resolve


def static_site_transport(root: Path, host: str) -> httpx2.MockTransport:
    def handle(request: httpx2.Request) -> httpx2.Response:
        if request.headers.get("host") != host:
            return httpx2.Response(404)
        path = (root / request.url.path.lstrip("/")).resolve()
        if path.is_dir():
            path = path / "index.html"
        if not path.is_relative_to(root.resolve()) or not path.is_file():
            return httpx2.Response(404, text="not found")
        content_type = CONTENT_TYPES.get(path.suffix, "application/octet-stream")
        return httpx2.Response(
            200, headers={"content-type": content_type}, content=path.read_bytes()
        )

    return httpx2.MockTransport(handle)
