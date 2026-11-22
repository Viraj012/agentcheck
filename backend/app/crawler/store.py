"""Persist crawled pages for a run."""

from collections.abc import Sequence
from uuid import UUID

import psycopg

from app.crawler.crawl import CrawledPage

INSERT_PAGE = """
INSERT INTO pages (run_id, url, title, content_hash, text)
VALUES (%s, %s, %s, %s, %s)
"""


async def save_pages(
    conn: psycopg.AsyncConnection, run_id: UUID | str, pages: Sequence[CrawledPage]
) -> int:
    if not pages:
        return 0
    async with conn.cursor() as cursor:
        await cursor.executemany(
            INSERT_PAGE,
            [(run_id, page.url, page.title, page.content_hash, page.text) for page in pages],
        )
    return len(pages)
