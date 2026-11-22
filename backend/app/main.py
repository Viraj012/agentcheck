from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.chat import router as chat_router
from app.config import APP_NAME, get_settings
from app.llm.limits import TokenBucket


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    application.state.limiter = TokenBucket(settings.llm_rpm, burst=settings.llm_burst)
    yield


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

    application.include_router(chat_router)
    return application


app = create_app()
