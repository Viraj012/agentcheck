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
from app.security import hash_ip

router = APIRouter()

TAKE_CHAT_SLOT = """
INSERT INTO chat_usage (run_id, ip_hash, count) VALUES (%(run_id)s, %(ip_hash)s, 1)
ON CONFLICT (run_id, ip_hash) DO UPDATE SET count = chat_usage.count + 1
WHERE chat_usage.count < %(limit)s
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
    visitor = hash_ip(
        request.client.host if request.client else "unknown",
        settings.ip_hash_salt.get_secret_value(),
    )
    if not await _take_chat_slot(conn, run_id, visitor, settings.chat_limit):
        raise HTTPException(429, f"chat limit of {settings.chat_limit} messages reached")
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
    conn: psycopg.AsyncConnection, run_id: UUID, ip_hash: str, limit: int
) -> bool:
    """Atomically count one message; False once the visitor has used `limit` messages."""
    cursor = await conn.execute(
        TAKE_CHAT_SLOT, {"run_id": run_id, "ip_hash": ip_hash, "limit": limit}
    )
    taken = await cursor.fetchone() is not None
    await conn.commit()
    return taken
