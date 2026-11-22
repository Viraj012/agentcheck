"""The only way the crawler talks to the network.

Every hop (the first request and each redirect) is normalized, resolved and checked by
the SSRF guard, then sent to the exact IP that passed the check. Redirects are followed
here by hand, never by the HTTP client, so no hop can skip the guard.
"""

from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx2

from app.config import APP_NAME, Settings
from app.crawler.ssrf import Resolver, resolve_public, system_resolver
from app.crawler.urls import normalize_url

BOT_NAME = f"{APP_NAME}Bot"
USER_AGENT = f"{BOT_NAME}/0.1 (help-center readiness check; respects robots.txt)"
REDIRECT_STATUSES = {301, 302, 303, 307, 308}


class FetchError(Exception):
    """The page could not be fetched: network error, too big, wrong type, too many redirects."""


@dataclass(frozen=True)
class FetchResult:
    url: str
    status: int
    content_type: str
    body: bytes


class SafeFetcher:
    def __init__(
        self,
        settings: Settings,
        *,
        resolver: Resolver = system_resolver,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        self._resolver = resolver
        self._max_redirects = settings.max_redirects
        self._max_bytes = settings.max_page_bytes
        self._client = httpx2.AsyncClient(
            transport=transport,
            follow_redirects=False,
            trust_env=False,
            timeout=settings.request_timeout_s,
            headers={"User-Agent": USER_AGENT},
        )

    async def fetch(self, url: str, *, accept: set[str]) -> FetchResult:
        current = normalize_url(url)
        for _ in range(self._max_redirects + 1):
            result, location = await self._fetch_one(current, accept)
            if location is None:
                return result
            current = normalize_url(urljoin(current, location))
        raise FetchError(f"more than {self._max_redirects} redirects starting at {url}")

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _fetch_one(self, url: str, accept: set[str]) -> tuple[FetchResult, str | None]:
        parts = urlsplit(url)
        host = parts.hostname or ""
        ip = (await resolve_public(host, self._resolver))[0]
        pinned_host = f"[{ip}]" if ":" in ip else ip
        pinned_url = urlunsplit((parts.scheme, pinned_host, parts.path, parts.query, ""))
        try:
            async with self._client.stream(
                "GET",
                pinned_url,
                headers={"Host": parts.netloc},
                extensions={"sni_hostname": host},
            ) as response:
                content_type = response.headers.get("content-type", "").split(";")[0].strip()
                location = response.headers.get("location")
                if response.status_code in REDIRECT_STATUSES and location:
                    return FetchResult(url, response.status_code, content_type, b""), location
                if response.status_code != 200:
                    return FetchResult(url, response.status_code, content_type, b""), None
                if content_type.lower() not in accept:
                    raise FetchError(f"unsupported content type {content_type!r} at {url}")
                body = await self._read_capped(response, url)
        except httpx2.HTTPError as exc:
            raise FetchError(f"request to {url} failed: {exc}") from exc
        return FetchResult(url, 200, content_type, body), None

    async def _read_capped(self, response: httpx2.Response, url: str) -> bytes:
        body = bytearray()
        async for chunk in response.aiter_bytes():
            body.extend(chunk)
            if len(body) > self._max_bytes:
                raise FetchError(f"{url} is larger than {self._max_bytes} bytes")
        return bytes(body)
