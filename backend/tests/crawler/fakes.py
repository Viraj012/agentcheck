"""Test doubles for the network. The SSRF guard itself is never replaced."""

from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path

import httpx2


def fake_resolver(mapping: Mapping[str, list[str]]) -> Callable[[str], Awaitable[list[str]]]:
    """Resolve names from a fixed table; unknown names fail like NXDOMAIN."""

    async def resolve(host: str) -> list[str]:
        if host not in mapping:
            raise OSError(f"cannot resolve {host}")
        return list(mapping[host])

    return resolve


CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".xml": "application/xml",
    ".css": "text/css",
}


def site_transport(root: Path, host: str) -> httpx2.MockTransport:
    """Serve a folder of static files for one host, like a tiny web server with no sockets."""

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


class LoopbackTransport(httpx2.AsyncBaseTransport):
    """Send every request to a local test server, after the SSRF guard has already
    checked (and pinned) the public address the fake resolver gave for the host."""

    def __init__(self, port: int) -> None:
        self._inner = httpx2.AsyncHTTPTransport()
        self._port = port

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        request.url = request.url.copy_with(scheme="http", host="127.0.0.1", port=self._port)
        return await self._inner.handle_async_request(request)

    async def aclose(self) -> None:
        await self._inner.aclose()
