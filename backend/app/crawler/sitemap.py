"""sitemap.xml discovery: robots.txt `Sitemap:` lines, else /sitemap.xml; one level of index."""

import xml.etree.ElementTree as ET
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

from app.crawler.fetch import FetchError, SafeFetcher
from app.crawler.ssrf import BlockedAddressError
from app.crawler.urls import InvalidURLError, in_scope, normalize_url

SITEMAP_TYPES = {"application/xml", "text/xml", "text/plain"}
FETCH_ERRORS = (FetchError, BlockedAddressError, InvalidURLError)


def parse_sitemap(body: bytes) -> tuple[list[str], list[str]]:
    """Return (page URLs, child sitemap URLs). Documents with a DOCTYPE are refused,
    which rules out entity-expansion attacks without an extra XML library."""
    if b"<!DOCTYPE" in body.upper():
        return [], []
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return [], []
    locs = [el.text.strip() for el in root.iter() if _local(el.tag) == "loc" and el.text]
    if _local(root.tag) == "sitemapindex":
        return [], locs
    return locs, []


async def discover_sitemap_urls(
    fetcher: SafeFetcher, start_url: str, robots: RobotFileParser, *, limit: int
) -> list[str]:
    origin = "{0.scheme}://{0.netloc}".format(urlsplit(start_url))
    sitemaps = [url for url in (robots.site_maps() or []) if url.startswith(origin)]
    pages, children = await _fetch_sitemaps(fetcher, sitemaps or [f"{origin}/sitemap.xml"])
    nested, _ = await _fetch_sitemaps(fetcher, [url for url in children if url.startswith(origin)])
    found: list[str] = []
    for raw in pages + nested:
        try:
            url = normalize_url(raw)
        except InvalidURLError:
            continue
        if in_scope(url, start_url) and url not in found:
            found.append(url)
        if len(found) >= limit:
            break
    return found


async def _fetch_sitemaps(fetcher: SafeFetcher, urls: list[str]) -> tuple[list[str], list[str]]:
    pages: list[str] = []
    children: list[str] = []
    for url in urls:
        try:
            result = await fetcher.fetch(url, accept=SITEMAP_TYPES)
        except FETCH_ERRORS:
            continue
        if result.status == 200:
            found_pages, found_children = parse_sitemap(result.body)
            pages += found_pages
            children += found_children
    return pages, children


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]
