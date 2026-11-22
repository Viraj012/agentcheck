"""Test doubles for the network. The SSRF guard itself is never replaced."""

import httpx2

from app.crawler.local_site import static_resolver, static_site_transport

fake_resolver = static_resolver
site_transport = static_site_transport


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
