"""robots.txt handling. Policy follows common crawler practice:
missing (4xx) means allow everything; unreachable (5xx, network error) means allow nothing.
A blocked address is not a robots question: BlockedAddressError propagates to the caller."""

from urllib.robotparser import RobotFileParser

from app.crawler.fetch import BOT_NAME, FetchError, SafeFetcher
from app.crawler.urls import InvalidURLError

ROBOTS_TYPES = {"text/plain", "text/html", "application/octet-stream", ""}


async def load_robots(fetcher: SafeFetcher, origin: str) -> RobotFileParser:
    robots = RobotFileParser(f"{origin}/robots.txt")
    try:
        result = await fetcher.fetch(f"{origin}/robots.txt", accept=ROBOTS_TYPES)
    except (FetchError, InvalidURLError):
        robots.disallow_all = True
        return robots
    if result.status >= 500:
        robots.disallow_all = True
    elif result.status >= 400:
        robots.allow_all = True
    else:
        robots.parse(result.body.decode("utf-8", errors="replace").splitlines())
    return robots


def can_fetch(robots: RobotFileParser, url: str) -> bool:
    return robots.can_fetch(BOT_NAME, url)
