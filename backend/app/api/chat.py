"""Chat with a report's support agent."""

from uuid import UUID

import psycopg
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.agent.agent import AgentQuestion, answer_questions
from app.agent.prompt import PROMPT_VERSION
from app.deps import ChatLLMDep, ConnDep, SettingsDep
from app.llm.base import LLMError
from app.retrieval.search import hybrid_search
from app.security import client_ip, hash_ip

router = APIRouter()

TAKE_CHAT_SLOT = """
INSERT INTO chat_usage (run_id, ip_hash, count) VALUES (%(run_id)s, %(ip_hash)s, 1)
ON CONFLICT (run_id, ip_hash) DO UPDATE SET count = chat_usage.count + 1
WHERE chat_usage.count < %(limit)s
RETURNING count
"""

TAKE_DAILY_SLOT = """
INSERT INTO chat_daily (day, count) VALUES (current_date, 1)
ON CONFLICT (day) DO UPDATE SET count = chat_daily.count + 1
WHERE chat_daily.count < %(limit)s
RETURNING count
"""


class ChatRequest(BaseModel):
    message: str


class Citation(BaseModel):
    id: int
    page_url: str
    title: str
    heading_path: str


class ChatResponse(BaseModel):
    answer: str
    abstained: bool
    citations: list[Citation]
    prompt_version: str


@router.post("/api/reports/{run_id}/chat")
async def chat(
    run_id: UUID,
    body: ChatRequest,
    request: Request,
    conn: ConnDep,
    llm: ChatLLMDep,
    settings: SettingsDep,
) -> ChatResponse:
    message = body.message.strip()
    if not message or len(message) > settings.chat_max_chars:
        raise HTTPException(422, f"message must be 1 to {settings.chat_max_chars} characters")
    if not await _has_chunks(conn, run_id):
        raise HTTPException(404, "report not found")
    visitor = hash_ip(client_ip(request, settings), settings.ip_hash_salt.get_secret_value())
    refusal = await _take_chat_slot(conn, run_id, visitor, settings)
    if refusal:
        raise HTTPException(429, refusal)
    try:
        (embedding,) = await llm.embed([message], task="query")
        chunks = await hybrid_search(conn, run_id, message, embedding, settings)
        (result,) = await answer_questions(llm, [AgentQuestion(1, message, chunks)])
    except LLMError as exc:
        raise HTTPException(503, "the assistant is unavailable right now, try again later") from exc
    by_id = {chunk.id: chunk for chunk in chunks}
    return ChatResponse(
        answer=result.answer,
        abstained=result.abstained,
        citations=[
            Citation(
                id=c,
                page_url=by_id[c].page_url,
                title=by_id[c].title,
                heading_path=by_id[c].heading_path,
            )
            for c in result.citations
        ],
        prompt_version=PROMPT_VERSION,
    )


async def _has_chunks(conn: psycopg.AsyncConnection, run_id: UUID) -> bool:
    cursor = await conn.execute("SELECT EXISTS (SELECT 1 FROM chunks WHERE run_id = %s)", (run_id,))
    return bool((await cursor.fetchone())[0])


async def _take_chat_slot(
    conn: psycopg.AsyncConnection, run_id: UUID, ip_hash: str, settings: SettingsDep
) -> str | None:
    """Atomically count one message against the visitor's and the global daily limit.

    Returns None when allowed, or the reason it was refused (nothing is counted then).
    """
    cursor = await conn.execute(
        TAKE_CHAT_SLOT, {"run_id": run_id, "ip_hash": ip_hash, "limit": settings.chat_limit}
    )
    if await cursor.fetchone() is None:
        await conn.rollback()
        return f"You've used all {settings.chat_limit} questions for this report."
    cursor = await conn.execute(TAKE_DAILY_SLOT, {"limit": settings.max_chats_per_day})
    if await cursor.fetchone() is None:
        await conn.rollback()
        return "The assistant has answered as many questions as it can today. Try again tomorrow."
    await conn.commit()
    return None
