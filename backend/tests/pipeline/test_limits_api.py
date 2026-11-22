import asyncio

import httpx2
import pytest

from app.config import Settings, get_settings
from app.db import connect
from app.deps import get_conn, get_turnstile
from app.main import create_app
from tests.pipeline.test_run import START
from tests.pipeline.test_runs_api import finished_run

pytestmark = pytest.mark.db


def client_for(migrated_url: str, settings: Settings, *, human: bool = True) -> httpx2.AsyncClient:
    app = create_app()

    async def test_conn():
        async with await connect(migrated_url) as c:
            yield c

    async def fake_turnstile(token: str | None, ip: str) -> bool:
        return human

    app.dependency_overrides[get_conn] = test_conn
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_turnstile] = lambda: fake_turnstile
    return httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://test")


def body(i: int) -> dict:
    return {"url": f"https://site{i}.example.com/help", "turnstile_token": "t"}


async def test_per_visitor_daily_limit(migrated_url, clean_conn) -> None:
    settings = Settings(_env_file=None, runs_per_ip_per_day=2, max_runs_per_day=30)
    async with client_for(migrated_url, settings) as client:
        codes = [(await client.post("/api/runs", json=body(i))).status_code for i in range(3)]
        blocked = await client.post("/api/runs", json=body(9))
    assert codes == [200, 200, 429]
    assert blocked.json()["limit"] == "per_visitor"


async def test_global_daily_limit(migrated_url, clean_conn) -> None:
    await clean_conn.execute(
        "INSERT INTO runs (start_url, normalized_url, ip_hash)"
        " SELECT 'u', 'https://other' || g || '.test/', 'someone-else' FROM generate_series(1, 3) g"
    )
    await clean_conn.commit()
    settings = Settings(_env_file=None, runs_per_ip_per_day=5, max_runs_per_day=3)
    async with client_for(migrated_url, settings) as client:
        response = await client.post("/api/runs", json=body(1))
    assert response.status_code == 429
    assert response.json()["limit"] == "global"


async def test_cached_report_does_not_count_toward_limits(migrated_url, clean_conn) -> None:
    await finished_run(clean_conn)
    settings = Settings(_env_file=None, runs_per_ip_per_day=1, max_runs_per_day=1)
    async with client_for(migrated_url, settings) as client:
        first = await client.post("/api/runs", json={"url": START, "turnstile_token": "t"})
        second = await client.post("/api/runs", json={"url": START, "turnstile_token": "t"})
    assert first.json()["cached"] and second.json()["cached"]


async def test_concurrent_requests_cannot_exceed_the_limit(migrated_url, clean_conn) -> None:
    settings = Settings(_env_file=None, runs_per_ip_per_day=2, max_runs_per_day=30)
    async with client_for(migrated_url, settings) as client:
        responses = await asyncio.gather(
            *(client.post("/api/runs", json=body(i)) for i in range(6))
        )
    assert sorted(r.status_code for r in responses) == [200, 200, 429, 429, 429, 429]


async def test_failed_bot_check_is_403_and_creates_nothing(migrated_url, clean_conn) -> None:
    settings = Settings(_env_file=None)
    async with client_for(migrated_url, settings, human=False) as client:
        response = await client.post("/api/runs", json=body(1))
    assert response.status_code == 403
    count = await (await clean_conn.execute("SELECT count(*) FROM runs")).fetchone()
    assert count == (0,)
