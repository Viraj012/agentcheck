import pytest

from app.crawler.crawl import CrawledPage
from app.crawler.store import save_pages
from app.db import connect

pytestmark = pytest.mark.db

PAGES = [
    CrawledPage("https://x.test/", "Home", "Welcome text", "h1"),
    CrawledPage("https://x.test/returns", "Returns", "Return within 30 days", "h2"),
]


async def test_save_pages_writes_rows_for_the_run(migrated_url: str) -> None:
    async with await connect(migrated_url) as conn:
        run_id = (
            await (
                await conn.execute(
                    "INSERT INTO runs (start_url, normalized_url) VALUES ('u', 'u') RETURNING id"
                )
            ).fetchone()
        )[0]
        assert await save_pages(conn, run_id, PAGES) == 2
        rows = await (
            await conn.execute(
                "SELECT url, title, text, content_hash FROM pages WHERE run_id = %s ORDER BY id",
                (run_id,),
            )
        ).fetchall()
        await conn.rollback()
    assert rows == [(p.url, p.title, p.text, p.content_hash) for p in PAGES]


async def test_save_pages_with_no_pages_is_a_no_op(migrated_url: str) -> None:
    async with await connect(migrated_url) as conn:
        assert await save_pages(conn, "00000000-0000-0000-0000-000000000000", []) == 0
