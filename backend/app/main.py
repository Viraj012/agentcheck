from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import APP_NAME, get_settings


def create_app() -> FastAPI:
    application = FastAPI(title=APP_NAME)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=get_settings().cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    @application.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "app": APP_NAME}

    return application


app = create_app()
