from functools import lru_cache
from pathlib import Path
from typing import Literal, cast

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "KPI Voice Helpdesk"
    environment: str = "development"
    api_prefix: str = "/api/v1"

    database_url: str = "postgresql+asyncpg://kpi_helpdesk:kpi_helpdesk@localhost:5432/kpi_helpdesk"

    jwt_secret_key: str = Field(
        default="change-this-development-secret-key-please",
        min_length=32,
    )
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 14
    cookie_secure: bool = False
    cookie_domain: str | None = None
    cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://127.0.0.1:3000"]
    )
    allowed_hosts: list[str] = Field(
        default_factory=lambda: ["localhost", "127.0.0.1", "host.docker.internal", "testserver"]
    )
    security_headers_enabled: bool = True

    audio_storage_dir: Path = PROJECT_ROOT / "backend/storage/audio"
    max_audio_mb: int = 30
    allowed_audio_mime_types: list[str] = Field(
        default_factory=lambda: [
            "audio/webm",
            "audio/wav",
            "audio/x-wav",
            "audio/mpeg",
            "audio/mp4",
            "audio/ogg",
        ]
    )

    whisper_model_size: str = "medium"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"
    whisper_beam_size: int = Field(default=1, ge=1, le=5)
    stt_warmup_on_startup: bool = True

    llm_base_model: str = "Qwen/Qwen3-1.7B"
    lora_adapter_path: Path = PROJECT_ROOT / "ml/models/qwen3-kpi-lora"
    llm_device: str = "auto"
    classifier_max_new_tokens: int = 128
    classifier_warmup_on_startup: bool = True
    voice_assistant_use_llm: bool = True
    voice_assistant_reuse_classifier_model: bool = True
    voice_assistant_max_new_tokens: int = Field(default=320, ge=32, le=2000)
    voice_assistant_min_confidence: float = Field(default=0.5, ge=0, le=1)
    voice_assistant_max_context_items: int = Field(default=3, ge=1, le=5)
    voice_assistant_tts_enabled: bool = True
    voice_assistant_tts_voice: str = "uk-UA-PolinaNeural"
    voice_assistant_tts_rate: str = "+0%"
    voice_assistant_tts_max_chars: int = Field(default=900, ge=100, le=4000)
    pbx_internal_token: str = Field(
        default="change-this-pbx-token-for-development",
        min_length=24,
    )

    @field_validator("audio_storage_dir", "lora_adapter_path", mode="after")
    @classmethod
    def resolve_project_relative_path(cls, value: Path) -> Path:
        if value.is_absolute():
            return value
        return (PROJECT_ROOT / value).resolve()

    @field_validator("cookie_samesite", mode="after")
    @classmethod
    def validate_cookie_samesite(cls, value: str) -> Literal["lax", "strict", "none"]:
        normalized = value.lower()
        if normalized not in {"lax", "strict", "none"}:
            raise ValueError("COOKIE_SAMESITE must be one of: lax, strict, none.")
        return cast(Literal["lax", "strict", "none"], normalized)

    @model_validator(mode="after")
    def validate_production_security(self) -> "Settings":
        if self.environment == "development":
            return self
        if self.jwt_secret_key.startswith("change-this"):
            raise RuntimeError("JWT_SECRET_KEY must be changed outside development.")
        if not self.cookie_secure:
            raise RuntimeError("COOKIE_SECURE must be true outside development.")
        if self.cookie_samesite == "none" and not self.cookie_secure:
            raise RuntimeError("COOKIE_SAMESITE=none requires secure cookies.")
        if "*" in self.cors_origins:
            raise RuntimeError("CORS_ORIGINS cannot contain '*' outside development.")
        if "*" in self.allowed_hosts:
            raise RuntimeError("ALLOWED_HOSTS cannot contain '*' outside development.")
        if self.pbx_internal_token.startswith("change-this"):
            raise RuntimeError("PBX_INTERNAL_TOKEN must be changed outside development.")
        return self

    @property
    def max_audio_bytes(self) -> int:
        return self.max_audio_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
