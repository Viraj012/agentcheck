"""FastAPI dependencies. Tests override these to inject a test database and a fake LLM."""

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Annotated

import httpx2
import psycopg
from fastapi import Depends, Request

from app.config import Settings, get_settings
from app.db import connect
from app.llm.base import LLMClient
from app.llm.gemini import GeminiLLMClient
from app.llm.limits import CallBudget, Usage
from app.security import verify_turnstile

SettingsDep = Annotated[Settings, Depends(get_settings)]


async def get_conn(settings: SettingsDep) -> AsyncIterator[psycopg.AsyncConnection]:
    conn = await connect(settings.database_url)
    try:
        yield conn
    finally:
        await conn.close()


def get_chat_llm(request: Request, settings: SettingsDep) -> LLMClient:
    """A Gemini client for one chat message: shared rate limiter, small call budget."""
    return GeminiLLMClient(
        settings,
        limiter=request.app.state.limiter,
        embed_limiter=request.app.state.embed_limiter,
        budget=CallBudget(settings.chat_llm_calls),
        usage=Usage(),
    )


TurnstileCheck = Callable[[str | None, str], Awaitable[bool]]


def get_turnstile(settings: SettingsDep) -> TurnstileCheck:
    async def check(token: str | None, ip: str) -> bool:
        async with httpx2.AsyncClient(timeout=10.0) as client:
            return await verify_turnstile(
                token, ip, secret=settings.turnstile_secret(), client=client
            )

    return check


ConnDep = Annotated[psycopg.AsyncConnection, Depends(get_conn)]
ChatLLMDep = Annotated[LLMClient, Depends(get_chat_llm)]
TurnstileDep = Annotated[TurnstileCheck, Depends(get_turnstile)]
