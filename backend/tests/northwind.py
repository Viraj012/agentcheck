"""Shared helpers: load the Northwind fixture pages and create runs in the test database."""

from pathlib import Path
from uuid import UUID

import psycopg

from app.crawler.crawl import CrawledPage
from app.crawler.extract import extract_page

SITE = Path(__file__).resolve().parents[2] / "fixtures" / "northwind" / "site"
BASE_URL = "https://northwind.test"


def page_path(file: Path) -> str:
    relative = file.relative_to(SITE)
    if relative.name == "index.html":
        parent = relative.parent.as_posix()
        return "/" if parent == "." else f"/{parent}/"
    return f"/{relative.as_posix()}"


def northwind_pages() -> list[CrawledPage]:
    pages = []
    for file in sorted(SITE.rglob("*.html")):
        path = page_path(file)
        if path.startswith("/internal/"):
            continue
        extracted = extract_page(file.read_text(), BASE_URL + path)
        pages.append(CrawledPage(BASE_URL + path, extracted.title, extracted.text, path))
    return pages


async def new_run(conn: psycopg.AsyncConnection) -> UUID:
    cursor = await conn.execute(
        "INSERT INTO runs (start_url, normalized_url) VALUES (%s, %s) RETURNING id",
        (BASE_URL + "/", BASE_URL + "/"),
    )
    return (await cursor.fetchone())[0]
