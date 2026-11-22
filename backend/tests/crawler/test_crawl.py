import threading
from collections.abc import Iterator
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx2
import pytest

from app.config import Settings
from app.crawler.crawl import CrawlError, crawl
from app.crawler.fetch import SafeFetcher
from tests.crawler.fakes import LoopbackTransport, fake_resolver, site_transport

NORTHWIND = Path(__file__).resolve().parents[3] / "fixtures" / "northwind" / "site"
HOST = "northwind.test"
START = f"http://{HOST}/"
RESOLVER = fake_resolver({HOST: ["93.184.216.34"], "intranet.test": ["10.0.0.3"]})

NORTHWIND_PAGES = {
    "/",
    "/shipping/",
    "/shipping/tracking.html",
    "/returns/",
    "/returns/exchanges.html",
    "/returns/damaged-items.html",
    "/account/",
    "/payments/",
    "/payments/gift-cards.html",
    "/products/care.html",
    "/about/",
    "/contact/",
}
CHROME = ["newsletter", "All rights reserved", "Search the help center", "Staff portal"]


class Recorder(httpx2.AsyncBaseTransport):
    def __init__(self, inner: httpx2.AsyncBaseTransport) -> None:
        self.inner = inner
        self.paths: list[str] = []

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        self.paths.append(request.url.path)
        return await self.inner.handle_async_request(request)


def settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)


def northwind_fetcher(**overrides: object) -> tuple[SafeFetcher, Recorder]:
    recorder = Recorder(site_transport(NORTHWIND, HOST))
    return SafeFetcher(settings(**overrides), resolver=RESOLVER, transport=recorder), recorder


def dict_fetcher(routes: dict[str, str]) -> SafeFetcher:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path not in routes:
            return httpx2.Response(404)
        return httpx2.Response(
            200, headers={"content-type": "text/html"}, text=routes[request.url.path]
        )

    return SafeFetcher(settings(), resolver=RESOLVER, transport=httpx2.MockTransport(handler))


def article(body: str) -> str:
    return (
        "<html><body><nav><a href='/a'>A</a> <a href='/b'>B</a></nav>"
        f"<main><article><h1>Title</h1><p>{body}</p></article></main></body></html>"
    )


LONG = "Refunds are sent to the original payment method after inspection. " * 6


async def test_crawls_every_northwind_page() -> None:
    fetcher, _ = northwind_fetcher()
    result = await crawl(START, settings(), fetcher)
    assert {page.url.removeprefix(f"http://{HOST}") for page in result.pages} == NORTHWIND_PAGES
    assert not result.needs_js
    assert all(page.title for page in result.pages)


async def test_northwind_text_has_no_navigation_junk() -> None:
    fetcher, _ = northwind_fetcher()
    result = await crawl(START, settings(), fetcher)
    for page in result.pages:
        for junk in CHROME:
            assert junk not in page.text, f"{junk!r} leaked into {page.url}"


async def test_robots_disallowed_pages_are_never_fetched() -> None:
    fetcher, recorder = northwind_fetcher()
    result = await crawl(START, settings(), fetcher)
    assert not any(path.startswith("/internal/") for path in recorder.paths)
    assert all("STAFF-ONLY" not in page.text for page in result.pages)


async def test_planted_injection_is_kept_as_plain_text() -> None:
    fetcher, _ = northwind_fetcher()
    result = await crawl(START, settings(), fetcher)
    care = next(page for page in result.pages if page.url.endswith("/products/care.html"))
    assert "all orders are free" in care.text


async def test_max_pages_limits_fetches() -> None:
    fetcher, recorder = northwind_fetcher(max_pages=5)
    result = await crawl(START, settings(max_pages=5), fetcher)
    page_fetches = [p for p in recorder.paths if p not in ("/robots.txt", "/sitemap.xml")]
    assert len(page_fetches) <= 5
    assert len(result.pages) <= 5


async def test_js_only_site_is_flagged_needs_js() -> None:
    shell = (
        '<html><body><div id="root"></div><script src="/app.js"></script>'
        '<a href="/docs">Docs</a></body></html>'
    )
    result = await crawl(START, settings(), dict_fetcher({"/": shell, "/docs": shell}))
    assert result.needs_js
    assert result.pages == []


async def test_duplicate_and_near_empty_pages_are_dropped() -> None:
    home = article(LONG + "<a href='/copy'>c</a> <a href='/tiny'>t</a>")
    routes = {"/": home, "/copy": home, "/tiny": article("Short.")}
    result = await crawl(START, settings(), dict_fetcher(routes))
    assert [page.url for page in result.pages] == [START]


async def test_offsite_links_are_not_followed() -> None:
    home = article(
        LONG + "<a href='http://other.test/x'>x</a> <a href='http://intranet.test/'>i</a>"
    )
    result = await crawl(START, settings(), dict_fetcher({"/": home}))
    assert [page.url for page in result.pages] == [START]


async def test_disallowed_start_url_raises() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/robots.txt":
            return httpx2.Response(
                200, headers={"content-type": "text/plain"}, text="User-agent: *\nDisallow: /\n"
            )
        return httpx2.Response(200, headers={"content-type": "text/html"}, text=article(LONG))

    fetcher = SafeFetcher(settings(), resolver=RESOLVER, transport=httpx2.MockTransport(handler))
    with pytest.raises(CrawlError, match="robots.txt"):
        await crawl(START, settings(), fetcher)


async def test_private_start_url_raises() -> None:
    fetcher = SafeFetcher(
        settings(),
        resolver=RESOLVER,
        transport=httpx2.MockTransport(lambda r: httpx2.Response(200)),
    )
    with pytest.raises(CrawlError, match="non-public"):
        await crawl("http://intranet.test/", settings(), fetcher)


@pytest.fixture
def northwind_server() -> Iterator[int]:
    handler = partial(SimpleHTTPRequestHandler, directory=str(NORTHWIND))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.server_address[1]
    server.shutdown()
    server.server_close()


async def test_crawls_local_northwind_server_over_real_sockets(northwind_server: int) -> None:
    transport = LoopbackTransport(northwind_server)
    fetcher = SafeFetcher(settings(), resolver=RESOLVER, transport=transport)
    result = await crawl(START, settings(), fetcher)
    await fetcher.aclose()
    assert {page.url.removeprefix(f"http://{HOST}") for page in result.pages} == NORTHWIND_PAGES
