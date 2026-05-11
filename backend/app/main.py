from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import auth, catalog, tickets, users
from app.core.config import get_settings

settings = get_settings()


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    Path(settings.audio_storage_dir).mkdir(parents=True, exist_ok=True)

    @app.get("/health", tags=["health"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(auth.router, prefix=settings.api_prefix)
    app.include_router(users.router, prefix=settings.api_prefix)
    app.include_router(catalog.router, prefix=settings.api_prefix)
    app.include_router(tickets.router, prefix=settings.api_prefix)
    app.include_router(tickets.operator_router, prefix=settings.api_prefix)
    return app


app = create_app()
