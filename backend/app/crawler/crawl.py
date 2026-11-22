"""Breadth-first crawl of one help center: robots.txt, sitemap or links, limits, dedupe."""

import asyncio
import hashlib
from collections import deque
from dataclasses import dataclass
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

from app.config import Settings
from app.crawler.extract import extract_links, extract_page
from app.crawler.fetch import FetchError, SafeFetcher
from app.crawler.robots import can_fetch, load_robots
from app.crawler.sitemap import discover_sitemap_urls
from app.crawler.ssrf import BlockedAddressError
from app.crawler.urls import InvalidURLError, in_scope, normalize_url

HTML_TYPES = {"text/html", "application/xhtml+xml"}
FETCH_ERRORS = (FetchError, BlockedAddressError, InvalidURLError)


class CrawlError(Exception):
    """The crawl cannot start or produced nothing usable; the message is shown to the user."""


@dataclass(frozen=True)
class CrawledPage:
    url: str
    title: str
    text: str
    content_hash: str


@dataclass(frozen=True)
class CrawlResult:
    pages: list[CrawledPage]
    needs_js: bool


@dataclass(frozen=True)
class _Visit:
    url: str
    title: str
    text: str
    links: list[str]


async def crawl(start_url: str, settings: Settings, fetcher: SafeFetcher) -> CrawlResult:
    try:
        start = normalize_url(start_url)
    except InvalidURLError as exc:
        raise CrawlError(str(exc)) from exc
    origin = "{0.scheme}://{0.netloc}".format(urlsplit(start))
    try:
        robots = await load_robots(fetcher, origin)
    except BlockedAddressError as exc:
        raise CrawlError(f"refusing to crawl {start}: {exc}") from exc
    if not can_fetch(robots, start):
        raise CrawlError(f"robots.txt does not allow crawling {start}")

    try:
        first = await _visit(fetcher, start)
    except FETCH_ERRORS as exc:
        raise CrawlError(f"could not fetch {start}: {exc}") from exc

    sitemap_urls = await discover_sitemap_urls(fetcher, start, robots, limit=settings.max_pages)
    visits = [first] if first else []
    seen = {start} | ({first.url} if first else set())
    queue = deque(url for url in sitemap_urls if url not in seen)
    seen.update(queue)
    _enqueue_links(first, start, robots, seen, queue)

    fetched = 1
    while queue and fetched < settings.max_pages:
        batch = [queue.popleft() for _ in range(min(settings.crawl_concurrency, len(queue)))]
        batch = batch[: settings.max_pages - fetched]
        fetched += len(batch)
        for visit in await asyncio.gather(*(_safe_visit(fetcher, url) for url in batch)):
            if visit and in_scope(visit.url, start):
                visits.append(visit)
                _enqueue_links(visit, start, robots, seen, queue)

    total_chars = sum(len(visit.text) for visit in visits)
    return CrawlResult(
        pages=_keep_unique(visits, settings.min_page_chars),
        needs_js=total_chars < settings.needs_js_min_chars,
    )


async def _visit(fetcher: SafeFetcher, url: str) -> _Visit | None:
    result = await fetcher.fetch(url, accept=HTML_TYPES)
    if result.status != 200:
        return None
    html = result.body.decode("utf-8", errors="replace")
    page = extract_page(html, result.url)
    return _Visit(result.url, page.title, page.text, extract_links(html, result.url))


async def _safe_visit(fetcher: SafeFetcher, url: str) -> _Visit | None:
    try:
        return await _visit(fetcher, url)
    except FETCH_ERRORS:
        return None


def _enqueue_links(
    visit: _Visit | None,
    start: str,
    robots: RobotFileParser,
    seen: set[str],
    queue: deque[str],
) -> None:
    if visit is None:
        return
    for link in visit.links:
        if link not in seen and in_scope(link, start) and can_fetch(robots, link):
            seen.add(link)
            queue.append(link)


def _keep_unique(visits: list[_Visit], min_chars: int) -> list[CrawledPage]:
    pages: list[CrawledPage] = []
    hashes: set[str] = set()
    for visit in visits:
        content_hash = hashlib.sha256(visit.text.encode()).hexdigest()
        if len(visit.text) < min_chars or content_hash in hashes:
            continue
        hashes.add(content_hash)
        pages.append(CrawledPage(visit.url, visit.title or visit.url, visit.text, content_hash))
    return pages
