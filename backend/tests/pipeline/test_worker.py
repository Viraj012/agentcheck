from collections.abc import AsyncIterator
from uuid import UUID

import psycopg
import pytest

from app.config import Settings
from app.db import connect
from app.pipeline.worker import claim_next_run, fail_exhausted_runs, process_one
from tests.pipeline.fake_pipeline_llm import pipeline_llm
from tests.pipeline.test_run import START, northwind_fetcher

pytestmark = pytest.mark.db

S = Settings(_env_file=None, stale_lock_s=300, max_attempts=2)


@pytest.fixture
async def conn(migrated_url: str) -> AsyncIterator[psycopg.AsyncConnection]:
    """Worker tests own the whole runs table of the throwaway test database."""
    connection = await connect(migrated_url)
    await connection.execute("DELETE FROM runs")
    await connection.commit()
    yield connection
    await connection.rollback()
    await connection.execute("DELETE FROM runs")
    await connection.commit()
    await connection.close()


async def add_run(
    conn: psycopg.AsyncConnection,
    status: str = "queued",
    *,
    minutes_ago: int = 0,
    attempts: int = 0,
    locked_minutes_ago: int | None = None,
) -> UUID:
    cursor = await conn.execute(
        """
        INSERT INTO runs (start_url, normalized_url, status, attempts, created_at, locked_at)
        VALUES (%s, %s, %s, %s, now() - make_interval(mins => %s),
                CASE WHEN %s::int IS NULL THEN NULL ELSE now() - make_interval(mins => %s) END)
        RETURNING id
        """,
        (START, START, status, attempts, minutes_ago, locked_minutes_ago, locked_minutes_ago or 0),
    )
    run_id = (await cursor.fetchone())[0]
    await conn.commit()
    return run_id


async def status_of(conn: psycopg.AsyncConnection, run_id: UUID) -> tuple:
    cursor = await conn.execute(
        "SELECT status, attempts, started_at IS NOT NULL, error FROM runs WHERE id = %s", (run_id,)
    )
    return await cursor.fetchone()


async def test_claims_oldest_queued_run(conn) -> None:
    await add_run(conn, minutes_ago=1)
    oldest = await add_run(conn, minutes_ago=5)
    claimed = await claim_next_run(conn, S)
    await conn.commit()
    assert claimed == (oldest, START, 1)
    assert (await status_of(conn, oldest))[:3] == ("running", 1, True)


async def test_nothing_to_claim(conn) -> None:
    await add_run(conn, "running", attempts=1, locked_minutes_ago=1)
    await add_run(conn, "done")
    assert await claim_next_run(conn, S) is None


async def test_stale_running_run_is_reclaimed(conn) -> None:
    stale = await add_run(conn, "running", attempts=1, locked_minutes_ago=10)
    assert await claim_next_run(conn, S) == (stale, START, 2)


async def test_exhausted_stale_run_is_failed_not_reclaimed(conn) -> None:
    stale = await add_run(conn, "running", attempts=2, locked_minutes_ago=10)
    assert await claim_next_run(conn, S) is None
    assert await fail_exhausted_runs(conn, S) == 1
    status, _, _, error = await status_of(conn, stale)
    assert status == "failed" and "interrupted" in error


async def test_concurrent_workers_never_claim_the_same_run(conn, migrated_url) -> None:
    first_run = await add_run(conn, minutes_ago=2)
    second_run = await add_run(conn, minutes_ago=1)
    async with await connect(migrated_url) as other:
        first = await claim_next_run(conn, S)
        second = await claim_next_run(other, S)
        assert {first[0], second[0]} == {first_run, second_run}
        await other.rollback()
    await conn.rollback()


async def test_process_one_runs_a_queued_check_to_done(conn, migrated_url) -> None:
    run_id = await add_run(conn)
    processed = await process_one(
        migrated_url,
        S,
        llm_factory=lambda budget, usage: pipeline_llm(S.embedding_dim),
        fetcher_factory=lambda: northwind_fetcher(S),
    )
    assert processed
    assert (await status_of(conn, run_id))[0] == "done"
    assert not await process_one(
        migrated_url,
        S,
        llm_factory=lambda b, u: pipeline_llm(S.embedding_dim),
        fetcher_factory=lambda: northwind_fetcher(S),
    )


async def test_run_killed_mid_crawl_is_restarted_cleanly(conn, migrated_url) -> None:
    run_id = await add_run(conn, "running", attempts=1, locked_minutes_ago=10)
    await conn.execute(
        "INSERT INTO pages (run_id, url, title, content_hash, text)"
        " VALUES (%s, 'u', 't', 'h', 'x')",
        (run_id,),
    )
    await conn.commit()
    await process_one(
        migrated_url,
        S,
        llm_factory=lambda b, u: pipeline_llm(S.embedding_dim),
        fetcher_factory=lambda: northwind_fetcher(S),
    )
    status, attempts, _, _ = await status_of(conn, run_id)
    pages = (
        await (
            await conn.execute("SELECT count(*) FROM pages WHERE run_id = %s", (run_id,))
        ).fetchone()
    )[0]
    assert (status, attempts, pages) == ("done", 2, 12)
