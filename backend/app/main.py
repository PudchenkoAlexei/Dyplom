from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import logging
import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.v1 import auth, catalog, phone_assistant, tickets, users, voice_assistant
from app.core.config import get_settings
from app.services.classifier import get_classifier_service
from app.services.stt import get_stt_service
from app.services.voice_assistant import get_phone_qwen_assistant_service

settings = get_settings()
logger = logging.getLogger("uvicorn.error")


def warm_up_classifier() -> None:
    if not settings.classifier_warmup_on_startup:
        logger.info("Classifier warmup is disabled.")
        return

    started_at = time.perf_counter()
    logger.info("Warming up classifier model...")
    get_classifier_service()
    logger.info(
        "Classifier model warmed up in %.2f seconds.",
        time.perf_counter() - started_at,
    )


def warm_up_stt() -> None:
    if not settings.stt_warmup_on_startup:
        logger.info("STT warmup is disabled.")
        return

    started_at = time.perf_counter()
    logger.info("Warming up speech-to-text model...")
    get_stt_service()
    logger.info(
        "Speech-to-text model warmed up in %.2f seconds.",
        time.perf_counter() - started_at,
    )


def warm_up_phone_assistant() -> None:
    if not settings.voice_assistant_phone_warmup_on_startup:
        logger.info("Phone assistant LLM warmup is disabled.")
        return
    if not settings.voice_assistant_use_llm or not settings.voice_assistant_phone_use_llm:
        logger.info("Phone assistant LLM warmup skipped because LLM is disabled.")
        return
    if settings.voice_assistant_phone_inference_engine == "openai_compatible":
        logger.info(
            "Phone assistant uses an external OpenAI-compatible LLM endpoint; "
            "local model warmup is skipped."
        )
        return

    started_at = time.perf_counter()
    logger.info("Warming up phone assistant LLM...")
    get_phone_qwen_assistant_service()
    logger.info(
        "Phone assistant LLM warmed up in %.2f seconds.",
        time.perf_counter() - started_at,
    )


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    warm_up_classifier()
    warm_up_stt()
    warm_up_phone_assistant()
    yield


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):  # type: ignore[no-untyped-def]
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=(), payment=()",
        )
        if settings.environment != "development" and settings.cookie_secure:
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )
        return response


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    if settings.allowed_hosts:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
    if settings.security_headers_enabled:
        app.add_middleware(SecurityHeadersMiddleware)
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
    app.include_router(voice_assistant.router, prefix=settings.api_prefix)
    app.include_router(phone_assistant.router, prefix=settings.api_prefix)
    return app


app = create_app()
