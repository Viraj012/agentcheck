import httpx2
import pytest

from app.config import APP_NAME, Settings
from app.crawler.fetch import FetchError, SafeFetcher
from app.crawler.ssrf import BlockedAddressError
from app.crawler.urls import InvalidURLError
from tests.crawler.fakes import fake_resolver

PUBLIC = "93.184.216.34"
HTML = {"content-type": "text/html; charset=utf-8"}
ACCEPT = {"text/html"}
RESOLVER = fake_resolver(
    {
        "help.example.com": [PUBLIC],
        "evil.example.com": [PUBLIC],
        "internal.example.com": ["10.0.0.9"],
        "localhost": ["127.0.0.1"],
    }
)


def make_fetcher(handler, **overrides: object) -> SafeFetcher:
    settings = Settings(_env_file=None, **overrides)
    return SafeFetcher(settings, resolver=RESOLVER, transport=httpx2.MockTransport(handler))


def redirect_to(location: str):
    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.headers["host"] == "evil.example.com":
            return httpx2.Response(302, headers={"location": location})
        return httpx2.Response(200, headers=HTML, text="internal secrets")

    return handler


async def test_fetches_public_page() -> None:
    fetcher = make_fetcher(lambda r: httpx2.Response(200, headers=HTML, text="<p>hi</p>"))
    result = await fetcher.fetch("https://help.example.com/a", accept=ACCEPT)
    assert (result.status, result.body, result.url) == (
        200,
        b"<p>hi</p>",
        "https://help.example.com/a",
    )


@pytest.mark.parametrize(
    "location",
    [
        "http://10.0.0.9/",
        "http://127.0.0.1/admin",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/",
        "http://localhost/",
        "http://internal.example.com/",
    ],
)
async def test_redirect_to_private_address_is_blocked(location: str) -> None:
    fetcher = make_fetcher(redirect_to(location))
    with pytest.raises(BlockedAddressError):
        await fetcher.fetch("https://evil.example.com/start", accept=ACCEPT)


async def test_redirect_to_disallowed_scheme_or_port_is_rejected() -> None:
    fetcher = make_fetcher(redirect_to("https://help.example.com:8443/"))
    with pytest.raises(InvalidURLError):
        await fetcher.fetch("https://evil.example.com/start", accept=ACCEPT)


async def test_public_redirect_is_followed() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/old":
            return httpx2.Response(301, headers={"location": "/new"})
        return httpx2.Response(200, headers=HTML, text="moved")

    result = await make_fetcher(handler).fetch("https://help.example.com/old", accept=ACCEPT)
    assert (result.url, result.body) == ("https://help.example.com/new", b"moved")


async def test_connection_is_pinned_to_the_checked_ip() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, headers=HTML, text="ok")

    await make_fetcher(handler).fetch("https://help.example.com/a?x=1", accept=ACCEPT)
    request = seen[0]
    assert request.url.host == PUBLIC
    assert request.url.raw_path == b"/a?x=1"
    assert request.headers["host"] == "help.example.com"
    assert request.extensions["sni_hostname"] == "help.example.com"
    assert request.headers["user-agent"].startswith(f"{APP_NAME}Bot/")


async def test_redirect_loop_stops_at_cap() -> None:
    calls = 0

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal calls
        calls += 1
        return httpx2.Response(302, headers={"location": "/loop"})

    with pytest.raises(FetchError, match="redirects"):
        await make_fetcher(handler, max_redirects=3).fetch(
            "https://help.example.com/loop", accept=ACCEPT
        )
    assert calls == 4


async def test_body_over_size_cap_is_rejected() -> None:
    fetcher = make_fetcher(
        lambda r: httpx2.Response(200, headers=HTML, content=b"x" * 2000), max_page_bytes=1000
    )
    with pytest.raises(FetchError, match="larger than"):
        await fetcher.fetch("https://help.example.com/big", accept=ACCEPT)


async def test_unaccepted_content_type_is_rejected() -> None:
    fetcher = make_fetcher(
        lambda r: httpx2.Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF")
    )
    with pytest.raises(FetchError, match="content type"):
        await fetcher.fetch("https://help.example.com/doc.pdf", accept=ACCEPT)


async def test_error_status_is_returned_without_body() -> None:
    fetcher = make_fetcher(lambda r: httpx2.Response(404, headers=HTML, text="not found"))
    result = await fetcher.fetch("https://help.example.com/missing", accept=ACCEPT)
    assert (result.status, result.body) == (404, b"")


async def test_network_error_becomes_fetch_error() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused", request=request)

    with pytest.raises(FetchError, match="refused"):
        await make_fetcher(handler).fetch("https://help.example.com/", accept=ACCEPT)
