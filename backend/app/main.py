import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.chat import router as chat_router
from app.api.runs import router as runs_router
from app.config import APP_NAME, Settings, get_settings
from app.crawler.fetch import SafeFetcher
from app.llm.gemini import GeminiLLMClient
from app.llm.limits import CallBudget, TokenBucket, Usage
from app.pipeline.worker import worker_loop


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    limiter = TokenBucket(settings.llm_rpm, burst=settings.llm_burst)
    application.state.limiter = limiter
    worker = asyncio.create_task(_worker(settings, limiter)) if settings.worker_enabled else None
    yield
    if worker is not None:
        worker.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await worker


async def _worker(settings: Settings, limiter: TokenBucket) -> None:
    def llm_factory(budget: CallBudget, usage: Usage) -> GeminiLLMClient:
        return GeminiLLMClient(settings, limiter=limiter, budget=budget, usage=usage)

    await worker_loop(
        settings.database_url,
        settings,
        llm_factory=llm_factory,
        fetcher_factory=lambda: SafeFetcher(settings),
    )


def create_app() -> FastAPI:
    application = FastAPI(title=APP_NAME, lifespan=lifespan)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=get_settings().cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    @application.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "app": APP_NAME}

    application.include_router(runs_router)
    application.include_router(chat_router)
    return application


app = create_app()
