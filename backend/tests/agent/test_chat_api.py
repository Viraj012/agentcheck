import asyncio
from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import httpx2
import pytest

from app.config import Settings, get_settings
from app.crawler.store import save_pages
from app.db import connect
from app.deps import get_chat_llm, get_conn
from app.indexing.store import index_run
from app.llm.fake import FakeLLMClient
from app.main import create_app
from tests.northwind import new_run, northwind_pages

pytestmark = pytest.mark.db

SETTINGS = Settings(_env_file=None, chat_limit=2)


@pytest.fixture
async def run_id(migrated_url: str) -> AsyncIterator[UUID]:
    """A committed, indexed Northwind run (the app reads it on its own connection)."""
    async with await connect(migrated_url) as conn:
        run = await new_run(conn)
        await save_pages(conn, run, northwind_pages())
        await index_run(conn, run, FakeLLMClient(dim=SETTINGS.embedding_dim), SETTINGS)
        await conn.commit()
    yield run
    async with await connect(migrated_url) as conn:
        await conn.execute("DELETE FROM runs WHERE id = %s", (run,))
        await conn.commit()


def make_client(
    migrated_url: str, llm: FakeLLMClient, settings: Settings = SETTINGS
) -> httpx2.AsyncClient:
    app = create_app()

    async def test_conn():
        async with await connect(migrated_url) as conn:
            yield conn

    app.dependency_overrides[get_conn] = test_conn
    app.dependency_overrides[get_chat_llm] = lambda: llm
    app.dependency_overrides[get_settings] = lambda: settings
    return httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://test")


def scripted_answer() -> FakeLLMClient:
    """Answers question 1 by citing the first chunk it was given."""

    def respond(prompt: str) -> dict:
        chunk_id = int(prompt.split('<chunk id="', 1)[1].split('"', 1)[0])
        answer = {"question_id": 1, "answer": "Gift cards never expire.", "citations": [chunk_id]}
        return {"answers": [answer | {"abstained": False}]}

    return FakeLLMClient(dim=SETTINGS.embedding_dim, responder=respond)


async def test_chat_returns_grounded_answer_with_citation_details(migrated_url, run_id) -> None:
    async with make_client(migrated_url, scripted_answer()) as client:
        response = await client.post(
            f"/api/reports/{run_id}/chat", json={"message": "Do gift cards expire?"}
        )
    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "Gift cards never expire."
    assert body["abstained"] is False
    assert body["prompt_version"] == "agent-v2"
    (citation,) = body["citations"]
    assert citation["page_url"].startswith("https://northwind.test/")
    assert set(citation) == {"id", "page_url", "title", "heading_path"}


async def test_unknown_run_is_404_without_llm_calls(migrated_url) -> None:
    llm = FakeLLMClient(dim=SETTINGS.embedding_dim)
    async with make_client(migrated_url, llm) as client:
        response = await client.post(f"/api/reports/{uuid4()}/chat", json={"message": "hi"})
    assert response.status_code == 404
    assert llm.calls == []


@pytest.mark.parametrize("message", ["", "   ", "x" * 501])
async def test_message_must_be_non_empty_and_short(migrated_url, run_id, message) -> None:
    async with make_client(migrated_url, scripted_answer()) as client:
        response = await client.post(f"/api/reports/{run_id}/chat", json={"message": message})
    assert response.status_code == 422


async def test_visitor_is_limited_per_report(migrated_url, run_id) -> None:
    async with make_client(migrated_url, scripted_answer()) as client:
        codes = [
            (
                await client.post(f"/api/reports/{run_id}/chat", json={"message": "gift cards?"})
            ).status_code
            for _ in range(3)
        ]
    assert codes == [200, 200, 429]


async def test_concurrent_messages_cannot_exceed_the_limit(migrated_url, run_id) -> None:
    async with make_client(migrated_url, scripted_answer()) as client:
        responses = await asyncio.gather(
            *(
                client.post(f"/api/reports/{run_id}/chat", json={"message": "gift cards?"})
                for _ in range(6)
            )
        )
    assert sorted(r.status_code for r in responses) == [200, 200, 429, 429, 429, 429]


async def test_global_daily_chat_cap(migrated_url, run_id) -> None:
    async with await connect(migrated_url) as conn:
        await conn.execute("DELETE FROM chat_daily")
        await conn.commit()
    capped = Settings(_env_file=None, chat_limit=10, max_chats_per_day=2)
    async with make_client(migrated_url, scripted_answer(), capped) as client:
        codes = []
        for i in range(3):
            response = await client.post(
                f"/api/reports/{run_id}/chat",
                json={"message": f"gift cards {i}?"},
            )
            codes.append(response.status_code)
    assert codes == [200, 200, 429]
