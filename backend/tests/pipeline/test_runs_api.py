from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import httpx2
import psycopg
import pytest

from app.config import Settings, get_settings
from app.db import connect
from app.deps import get_conn
from app.llm.limits import CallBudget, Usage
from app.main import create_app
from app.pipeline.run import execute_run
from tests.pipeline.fake_pipeline_llm import pipeline_llm
from tests.pipeline.test_run import START, northwind_fetcher

pytestmark = pytest.mark.db

S = Settings(_env_file=None, worker_enabled=False)


@pytest.fixture
async def conn(migrated_url: str) -> AsyncIterator[psycopg.AsyncConnection]:
    connection = await connect(migrated_url)
    await connection.execute("DELETE FROM runs")
    await connection.commit()
    yield connection
    await connection.rollback()
    await connection.execute("DELETE FROM runs")
    await connection.commit()
    await connection.close()


@pytest.fixture
def client(migrated_url: str) -> httpx2.AsyncClient:
    app = create_app()

    async def test_conn():
        async with await connect(migrated_url) as c:
            yield c

    app.dependency_overrides[get_conn] = test_conn
    app.dependency_overrides[get_settings] = lambda: S
    return httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://test")


async def finished_run(conn: psycopg.AsyncConnection) -> UUID:
    cursor = await conn.execute(
        "INSERT INTO runs (start_url, normalized_url, status)"
        " VALUES (%s, %s, 'running') RETURNING id",
        (START, START),
    )
    run_id = (await cursor.fetchone())[0]
    await conn.commit()
    await execute_run(
        conn,
        run_id,
        START,
        S,
        llm=pipeline_llm(S.embedding_dim),
        fetcher=northwind_fetcher(S),
        usage=Usage(),
        budget=CallBudget(20),
    )
    return run_id


async def test_create_run_queues_it(client, conn) -> None:
    async with client:
        response = await client.post("/api/runs", json={"url": "https://Help.Example.com/docs#x"})
    assert response.status_code == 200
    run_id = response.json()["run_id"]
    row = await (
        await conn.execute(
            "SELECT status, normalized_url, ip_hash FROM runs WHERE id = %s", (run_id,)
        )
    ).fetchone()
    assert row[0] == "queued" and row[1] == "https://help.example.com/docs" and len(row[2]) == 64


@pytest.mark.parametrize("url", ["ftp://example.com", "http://example.com:8080/", "not a url"])
async def test_invalid_url_is_422(client, url) -> None:
    async with client:
        response = await client.post("/api/runs", json={"url": url})
    assert response.status_code == 422


async def test_same_url_in_progress_reuses_the_run(client) -> None:
    async with client:
        first = (await client.post("/api/runs", json={"url": "https://example.com/help"})).json()
        second = (
            await client.post("/api/runs", json={"url": "https://EXAMPLE.com/help#top"})
        ).json()
    assert first["run_id"] == second["run_id"]


async def test_recent_report_is_served_from_cache(client, conn) -> None:
    run_id = await finished_run(conn)
    async with client:
        response = await client.post("/api/runs", json={"url": START})
    assert response.json() == {"report_id": str(run_id), "cached": True}


async def test_run_status(client, conn) -> None:
    run_id = await finished_run(conn)
    async with client:
        body = (await client.get(f"/api/runs/{run_id}")).json()
        missing = await client.get(f"/api/runs/{uuid4()}")
    assert body == {
        "run_id": str(run_id),
        "status": "done",
        "phase": "report",
        "progress": 1.0,
        "error": None,
        "report_id": str(run_id),
    }
    assert missing.status_code == 404


async def test_report_has_verdict_scores_failures_gaps_and_handover(client, conn) -> None:
    run_id = await finished_run(conn)
    await conn.execute(
        "UPDATE results SET verdict = 'incorrect', judge_reason = 'wrong' WHERE test_case_id ="
        " (SELECT min(id) FROM test_cases WHERE run_id = %s AND category = 'answerable')",
        (run_id,),
    )
    await conn.commit()
    async with client:
        body = (await client.get(f"/api/reports/{run_id}")).json()
        missing = await client.get(f"/api/reports/{uuid4()}")
    assert missing.status_code == 404
    assert body["verdict"] == "ready" and body["start_url"] == START
    assert body["category_scores"]["categories"]["answerable"]["total"] == 12
    assert body["gaps"]["missing_content"]
    assert body["handover"]["markdown"].startswith("# ")
    assert body["usage"]["pages"] == 12
    (failure,) = body["failures"]
    assert failure["verdict"] == "incorrect" and failure["judge_reason"] == "wrong"
    assert failure["retrieved"] and {"id", "page_url", "heading_path", "text"} <= set(
        failure["retrieved"][0]
    )
