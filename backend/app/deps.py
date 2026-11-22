"""FastAPI dependencies. Tests override these to inject a test database and a fake LLM."""

from collections.abc import AsyncIterator
from typing import Annotated

import psycopg
from fastapi import Depends, Request

from app.config import Settings, get_settings
from app.db import connect
from app.llm.base import LLMClient
from app.llm.gemini import GeminiLLMClient
from app.llm.limits import CallBudget, Usage

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
        budget=CallBudget(settings.chat_llm_calls),
        usage=Usage(),
    )


ConnDep = Annotated[psycopg.AsyncConnection, Depends(get_conn)]
ChatLLMDep = Annotated[LLMClient, Depends(get_chat_llm)]
