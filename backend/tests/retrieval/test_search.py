from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID

import psycopg
import pytest

from app.config import Settings
from app.crawler.crawl import CrawledPage
from app.crawler.extract import extract_page
from app.crawler.store import save_pages
from app.db import connect
from app.indexing.store import index_run
from app.llm.fake import FakeLLMClient
from app.retrieval.search import hybrid_search, keyword_search, vector_search

pytestmark = pytest.mark.db

SETTINGS = Settings(_env_file=None)
SITE = Path(__file__).resolve().parents[3] / "fixtures" / "northwind" / "site"


def northwind_pages() -> list[CrawledPage]:
    pages = []
    for path in sorted(SITE.rglob("*.html")):
        if "internal" in path.parts:
            continue
        page = extract_page(path.read_text(), f"https://northwind.test/{path.relative_to(SITE)}")
        pages.append(CrawledPage(page_url(path), page.title, page.text, str(path)))
    return pages


def page_url(path: Path) -> str:
    return f"https://northwind.test/{path.relative_to(SITE)}"


async def new_run(conn: psycopg.AsyncConnection) -> UUID:
    cursor = await conn.execute(
        "INSERT INTO runs (start_url, normalized_url) VALUES ('u', 'u') RETURNING id"
    )
    return (await cursor.fetchone())[0]


@pytest.fixture
async def conn(migrated_url: str) -> AsyncIterator[psycopg.AsyncConnection]:
    connection = await connect(migrated_url)
    yield connection
    await connection.rollback()
    await connection.close()


@pytest.fixture
async def indexed(conn: psycopg.AsyncConnection) -> tuple[UUID, FakeLLMClient]:
    run_id = await new_run(conn)
    await save_pages(conn, run_id, northwind_pages())
    llm = FakeLLMClient(dim=SETTINGS.embedding_dim)
    count = await index_run(conn, run_id, llm, SETTINGS)
    assert count >= 12
    return run_id, llm


async def chunk_text(conn: psycopg.AsyncConnection, chunk_id: int) -> str:
    cursor = await conn.execute("SELECT text FROM chunks WHERE id = %s", (chunk_id,))
    return (await cursor.fetchone())[0]


async def test_index_run_stores_embeddings_and_heading_paths(conn, indexed) -> None:
    run_id, llm = indexed
    cursor = await conn.execute(
        "SELECT count(*), count(embedding), count(*) FILTER (WHERE heading_path <> '')"
        " FROM chunks WHERE run_id = %s",
        (run_id,),
    )
    total, embedded, with_path = await cursor.fetchone()
    assert total == embedded == with_path
    embed_calls = [c for c in llm.calls if c.kind == "embed"]
    assert len(embed_calls) == total


async def test_keyword_search_finds_matching_chunks(conn, indexed) -> None:
    run_id, _ = indexed
    ids = await keyword_search(conn, run_id, "how do refunds work?", k=5)
    assert ids
    assert "refund" in (await chunk_text(conn, ids[0])).lower()


@pytest.mark.parametrize("query", ["the and of", "???", ""])
async def test_keyword_search_with_no_terms_returns_nothing(conn, indexed, query) -> None:
    run_id, _ = indexed
    assert await keyword_search(conn, run_id, query, k=5) == []


async def test_vector_search_ranks_identical_text_first(conn, indexed) -> None:
    run_id, llm = indexed
    cursor = await conn.execute(
        "SELECT id, text FROM chunks WHERE run_id = %s ORDER BY id LIMIT 1 OFFSET 3", (run_id,)
    )
    chunk_id, text = await cursor.fetchone()
    (embedding,) = await llm.embed([text], task="query")
    ids = await vector_search(conn, run_id, embedding, k=3)
    assert ids[0] == chunk_id
    assert len(ids) == 3


async def test_search_never_returns_other_runs(conn, indexed) -> None:
    run_id, llm = indexed
    other_run = await new_run(conn)
    await save_pages(conn, other_run, northwind_pages())
    await index_run(conn, other_run, llm, SETTINGS)
    cursor = await conn.execute("SELECT id FROM chunks WHERE run_id = %s", (run_id,))
    own = {row[0] for row in await cursor.fetchall()}
    (embedding,) = await llm.embed(["gift card balance"], task="query")
    assert set(await vector_search(conn, run_id, embedding, k=10)) <= own
    assert set(await keyword_search(conn, run_id, "gift card balance", k=10)) <= own


async def test_hybrid_search_returns_top_k_with_page_metadata(conn, indexed) -> None:
    run_id, llm = indexed
    query = "Do gift cards expire?"
    (embedding,) = await llm.embed([query], task="query")
    results = await hybrid_search(conn, run_id, query, embedding, SETTINGS)
    assert 0 < len(results) <= SETTINGS.retrieve_k
    assert results[0].page_url.startswith("https://northwind.test/")
    assert all(r.score > 0 for r in results)
    assert [r.score for r in results] == sorted((r.score for r in results), reverse=True)
    assert any("gift-cards" in r.page_url for r in results)
