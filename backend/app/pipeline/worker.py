"""Background worker: Postgres is the job queue.

`SELECT ... FOR UPDATE SKIP LOCKED` lets any number of workers claim runs without ever taking
the same one. A run whose heartbeat (locked_at, refreshed at every phase) is older than
STALE_LOCK_S was interrupted, for example by a restart: it is claimed again and restarted from
scratch, up to MAX_ATTEMPTS, after which it is marked failed. No run is left stuck.
"""

import asyncio
import logging
from collections.abc import Callable
from uuid import UUID

import psycopg

from app.config import Settings
from app.crawler.fetch import SafeFetcher
from app.db import connect
from app.llm.base import LLMClient
from app.llm.limits import CallBudget, Usage
from app.pipeline.run import execute_run
from app.pipeline.store import clear_run_data

log = logging.getLogger(__name__)

LLMFactory = Callable[[CallBudget, Usage], LLMClient]
FetcherFactory = Callable[[], SafeFetcher]

CLAIM_SQL = """
UPDATE runs
SET status = 'running', locked_at = now(), started_at = coalesce(started_at, now()),
    attempts = attempts + 1, error = NULL
WHERE id = (
    SELECT id FROM runs
    WHERE status = 'queued'
       OR (status = 'running'
           AND locked_at < now() - make_interval(secs => %(stale)s)
           AND attempts < %(max_attempts)s)
    ORDER BY created_at
    FOR UPDATE SKIP LOCKED
    LIMIT 1
)
RETURNING id, start_url, attempts
"""

FAIL_EXHAUSTED_SQL = """
UPDATE runs
SET status = 'failed', finished_at = now(), locked_at = NULL,
    error = 'the check was interrupted too many times; please try again'
WHERE status = 'running'
  AND locked_at < now() - make_interval(secs => %(stale)s)
  AND attempts >= %(max_attempts)s
"""


def _limits(settings: Settings) -> dict[str, int]:
    return {"stale": settings.stale_lock_s, "max_attempts": settings.max_attempts}


async def claim_next_run(
    conn: psycopg.AsyncConnection, settings: Settings
) -> tuple[UUID, str, int] | None:
    """Claim the oldest runnable run. The caller commits."""
    cursor = await conn.execute(CLAIM_SQL, _limits(settings))
    return await cursor.fetchone()


async def fail_exhausted_runs(conn: psycopg.AsyncConnection, settings: Settings) -> int:
    cursor = await conn.execute(FAIL_EXHAUSTED_SQL, _limits(settings))
    await conn.commit()
    return cursor.rowcount


async def process_one(
    database_url: str,
    settings: Settings,
    *,
    llm_factory: LLMFactory,
    fetcher_factory: FetcherFactory,
) -> bool:
    """Claim and run one check. Returns False when there was nothing to do."""
    async with await connect(database_url) as conn:
        await fail_exhausted_runs(conn, settings)
        claimed = await claim_next_run(conn, settings)
        await conn.commit()
        if claimed is None:
            return False
        run_id, start_url, _ = claimed
        await clear_run_data(conn, run_id)
        usage, budget = Usage(), CallBudget(settings.max_llm_calls_per_run)
        fetcher = fetcher_factory()
        try:
            status = await execute_run(
                conn,
                run_id,
                start_url,
                settings,
                llm=llm_factory(budget, usage),
                fetcher=fetcher,
                usage=usage,
                budget=budget,
            )
        finally:
            await fetcher.aclose()
        log.info("run %s finished: %s (%s LLM calls)", run_id, status, budget.used)
        return True


async def worker_loop(
    database_url: str,
    settings: Settings,
    *,
    llm_factory: LLMFactory,
    fetcher_factory: FetcherFactory,
) -> None:
    """Run checks one at a time until cancelled. Waits WORKER_POLL_S when the queue is empty."""
    while True:
        try:
            busy = await process_one(
                database_url, settings, llm_factory=llm_factory, fetcher_factory=fetcher_factory
            )
        except Exception:
            log.exception("worker iteration failed")
            busy = False
        if not busy:
            await asyncio.sleep(settings.worker_poll_s)
