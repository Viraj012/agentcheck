import httpx2
import pytest

from app.config import Settings
from app.crawler.extract import extract_links, extract_page
from app.crawler.fetch import SafeFetcher
from app.crawler.robots import can_fetch, load_robots
from app.crawler.sitemap import discover_sitemap_urls, parse_sitemap
from app.crawler.ssrf import BlockedAddressError
from tests.crawler.fakes import fake_resolver

ORIGIN = "https://help.example.com"
RESOLVER = fake_resolver({"help.example.com": ["93.184.216.34"]})


def fetcher_for(routes: dict[str, httpx2.Response]) -> SafeFetcher:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return routes.get(request.url.path, httpx2.Response(404))

    return SafeFetcher(
        Settings(_env_file=None), resolver=RESOLVER, transport=httpx2.MockTransport(handler)
    )


def text(body: str, content_type: str = "text/plain") -> httpx2.Response:
    return httpx2.Response(200, headers={"content-type": content_type}, text=body)


# robots.txt


async def test_robots_disallow_rules_apply_to_our_bot() -> None:
    fetcher = fetcher_for({"/robots.txt": text("User-agent: *\nDisallow: /private/\n")})
    robots = await load_robots(fetcher, ORIGIN)
    assert can_fetch(robots, f"{ORIGIN}/help/a")
    assert not can_fetch(robots, f"{ORIGIN}/private/x")


async def test_missing_robots_allows_everything() -> None:
    robots = await load_robots(fetcher_for({}), ORIGIN)
    assert can_fetch(robots, f"{ORIGIN}/anything")


async def test_robots_server_error_disallows_everything() -> None:
    fetcher = fetcher_for({"/robots.txt": httpx2.Response(503)})
    robots = await load_robots(fetcher, ORIGIN)
    assert not can_fetch(robots, f"{ORIGIN}/")


# sitemap

URLSET = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://help.example.com/a</loc></url>
  <url><loc> https://help.example.com/b </loc></url>
</urlset>"""

INDEX = b"""<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://help.example.com/sitemap-help.xml</loc></sitemap>
</sitemapindex>"""


def test_parse_urlset() -> None:
    assert parse_sitemap(URLSET) == (
        ["https://help.example.com/a", "https://help.example.com/b"],
        [],
    )


def test_parse_sitemap_index() -> None:
    assert parse_sitemap(INDEX) == ([], ["https://help.example.com/sitemap-help.xml"])


@pytest.mark.parametrize(
    "body",
    [
        b"not xml at all",
        b'<?xml version="1.0"?><!DOCTYPE lol [<!ENTITY a "aaaa">]>'
        b"<urlset><url><loc>&a;</loc></url></urlset>",
    ],
)
def test_parse_sitemap_rejects_malformed_or_doctype(body: bytes) -> None:
    assert parse_sitemap(body) == ([], [])


async def test_discover_follows_index_and_keeps_in_scope_urls() -> None:
    child = b"""<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://help.example.com/help/a</loc></url>
      <url><loc>https://help.example.com/blog/b</loc></url>
      <url><loc>https://other.example.com/help/c</loc></url>
    </urlset>"""
    fetcher = fetcher_for(
        {
            "/robots.txt": text(f"Sitemap: {ORIGIN}/sitemap.xml\n"),
            "/sitemap.xml": text(INDEX.decode(), "application/xml"),
            "/sitemap-help.xml": text(child.decode(), "text/xml"),
        }
    )
    robots = await load_robots(fetcher, ORIGIN)
    urls = await discover_sitemap_urls(fetcher, f"{ORIGIN}/help/", robots, limit=40)
    assert urls == [f"{ORIGIN}/help/a"]


async def test_discover_without_sitemap_returns_empty() -> None:
    fetcher = fetcher_for({})
    robots = await load_robots(fetcher, ORIGIN)
    assert await discover_sitemap_urls(fetcher, f"{ORIGIN}/", robots, limit=40) == []


# extraction

PAGE = """<html><head><title>Returns | Shop</title></head><body>
<nav><a href="/a">Home</a> <a href="/b">Shop</a></nav>
<main><article><h1>Returns</h1><h2>Window</h2>
<p>You can return most items within thirty days of delivery for a full refund to the original
payment method, as long as they are unused and in the original packaging.</p>
<h2>Labels</h2><p>We email a prepaid label after you start the return from your orders page.</p>
</article></main>
<footer>Copyright Shop Inc. Subscribe to our newsletter.</footer></body></html>"""


def test_extract_page_keeps_headings_and_drops_chrome() -> None:
    page = extract_page(PAGE, "https://help.example.com/returns")
    assert page.title == "Returns"
    assert "## Window" in page.text
    assert "thirty days" in page.text
    assert "newsletter" not in page.text
    assert "Home" not in page.text


def test_extract_page_handles_js_shell() -> None:
    shell = '<html><body><div id="root"></div><script src="/app.js"></script></body></html>'
    assert extract_page(shell, "https://help.example.com/").text == ""


def test_extract_links_resolves_and_filters() -> None:
    html = """<a href="/a#top">A</a><a href="b">B</a><a href="mailto:x@y.z">M</a>
    <a href="javascript:void(0)">J</a><a href="https://other.com/c">C</a><a>none</a>
    <a href="https://help.example.com:8443/d">D</a>"""
    assert extract_links(html, "https://help.example.com/help/") == [
        "https://help.example.com/a",
        "https://help.example.com/help/b",
        "https://other.com/c",
    ]


async def test_robots_redirect_to_private_address_propagates() -> None:
    fetcher = fetcher_for(
        {"/robots.txt": httpx2.Response(302, headers={"location": "http://10.0.0.1/"})}
    )
    with pytest.raises(BlockedAddressError):
        await load_robots(fetcher, ORIGIN)
