from collections.abc import AsyncIterator
from uuid import UUID

import httpx2
import psycopg
import pytest

from app.config import Settings
from app.crawler.fetch import SafeFetcher
from app.crawler.local_site import static_resolver, static_site_transport
from app.db import connect
from app.llm.limits import CallBudget, Usage
from app.pipeline.run import execute_run
from tests.northwind import SITE
from tests.pipeline.fake_pipeline_llm import pipeline_llm

pytestmark = pytest.mark.db

S = Settings(_env_file=None)
HOST = "northwind.test"
START = f"http://{HOST}/"


def northwind_fetcher(settings: Settings = S) -> SafeFetcher:
    return SafeFetcher(
        settings,
        resolver=static_resolver({HOST: ["93.184.216.34"]}),
        transport=static_site_transport(SITE, HOST),
    )


@pytest.fixture
async def conn(migrated_url: str) -> AsyncIterator[psycopg.AsyncConnection]:
    """Pipeline code commits, so delete the runs these tests create afterwards."""
    connection = await connect(migrated_url)
    yield connection
    await connection.rollback()
    await connection.execute("DELETE FROM runs WHERE start_url IN (%s, %s)", (START, BLOCKED))
    await connection.commit()
    await connection.close()


BLOCKED = "http://10.0.0.5/"


async def queued_run(conn: psycopg.AsyncConnection, url: str = START) -> UUID:
    cursor = await conn.execute(
        "INSERT INTO runs (start_url, normalized_url, status)"
        " VALUES (%s, %s, 'running') RETURNING id",
        (url, url),
    )
    run_id = (await cursor.fetchone())[0]
    await conn.commit()
    return run_id


async def fetch_one(conn: psycopg.AsyncConnection, sql: str, run_id: UUID) -> tuple:
    return await (await conn.execute(sql, (run_id,))).fetchone()


async def test_full_pipeline_on_northwind_with_fake_llm(conn) -> None:
    run_id = await queued_run(conn)
    llm = pipeline_llm(S.embedding_dim)
    usage = Usage()
    status = await execute_run(
        conn,
        run_id,
        START,
        S,
        llm=llm,
        fetcher=northwind_fetcher(),
        usage=usage,
        budget=CallBudget(20),
    )
    assert status == "done"
    run = await fetch_one(
        conn, "SELECT status, phase, progress, finished_at, error FROM runs WHERE id = %s", run_id
    )
    assert run[:3] == ("done", "report", 1.0) and run[3] is not None and run[4] is None
    pages, chunks, cases, graded = await _counts(conn, run_id)
    assert pages == 12 and chunks == 12
    assert cases == graded == 12 + 4 + 2 + 2
    score, verdict, categories, gaps, handover = await fetch_one(
        conn,
        "SELECT score, verdict, category_scores, gaps, handover FROM reports WHERE run_id = %s",
        run_id,
    )
    assert verdict == "ready" and score == pytest.approx(100.0)
    assert categories["categories"]["answerable"]["total"] == 12
    assert gaps["missing_content"][0]["questions"][1] == "Do you ship to Canada?"
    assert gaps["hard_to_find"] == []
    assert handover["markdown"].startswith("# ")
    assert handover["config"]["retrieval"]["retrieve_k"] == S.retrieve_k
    kinds = [c.kind for c in llm.calls]
    assert kinds.count("generate_json") == 1 + 3 + 3 + 1


async def _counts(conn: psycopg.AsyncConnection, run_id: UUID) -> tuple[int, int, int, int]:
    cursor = await conn.execute(
        """
        SELECT (SELECT count(*) FROM pages WHERE run_id = %(r)s),
               (SELECT count(*) FROM chunks WHERE run_id = %(r)s),
               (SELECT count(*) FROM test_cases WHERE run_id = %(r)s),
               (SELECT count(*) FROM results r JOIN test_cases t ON t.id = r.test_case_id
                 WHERE t.run_id = %(r)s AND r.verdict IS NOT NULL)
        """,
        {"r": run_id},
    )
    return await cursor.fetchone()


async def test_js_only_site_stops_as_needs_js(conn) -> None:
    shell = '<html><body><div id="root"></div><script src="/app.js"></script></body></html>'
    transport = httpx2.MockTransport(
        lambda r: httpx2.Response(200, headers={"content-type": "text/html"}, text=shell)
    )
    fetcher = SafeFetcher(
        S, resolver=static_resolver({HOST: ["93.184.216.34"]}), transport=transport
    )
    run_id = await queued_run(conn)
    llm = pipeline_llm(S.embedding_dim)
    status = await execute_run(
        conn, run_id, START, S, llm=llm, fetcher=fetcher, usage=Usage(), budget=CallBudget(20)
    )
    assert status == "needs_js"
    status_row = await fetch_one(conn, "SELECT status, error FROM runs WHERE id = %s", run_id)
    assert status_row[0] == "needs_js" and "JavaScript" in status_row[1]
    assert llm.calls == []


async def test_blocked_url_fails_cleanly(conn) -> None:
    run_id = await queued_run(conn, BLOCKED)
    status = await execute_run(
        conn,
        run_id,
        "http://10.0.0.5/",
        S,
        llm=pipeline_llm(S.embedding_dim),
        fetcher=northwind_fetcher(),
        usage=Usage(),
        budget=CallBudget(20),
    )
    assert status == "failed"
    status_row = await fetch_one(
        conn, "SELECT status, error, finished_at IS NOT NULL FROM runs WHERE id = %s", run_id
    )
    assert status_row[0] == "failed" and "non-public" in status_row[1] and status_row[2]


async def test_llm_failure_fails_cleanly_and_records_usage(conn) -> None:
    from app.llm.fake import FakeLLMClient

    run_id = await queued_run(conn)
    status = await execute_run(
        conn,
        run_id,
        START,
        S,
        llm=FakeLLMClient(dim=S.embedding_dim),
        fetcher=northwind_fetcher(),
        usage=Usage(calls=3, input_tokens=100, output_tokens=10),
        budget=CallBudget(20),
    )
    assert status == "failed"
    row = await fetch_one(
        conn, "SELECT status, error, input_tokens, phase FROM runs WHERE id = %s", run_id
    )
    assert (
        row[0] == "failed" and "AI service" in row[1] and row[2] == 100 and row[3] == "writing_exam"
    )
