from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
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
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://127.0.0.1:3000"]
    )

    audio_storage_dir: Path = PROJECT_ROOT / "backend/storage/audio"
    max_audio_mb: int = 30

    whisper_model_size: str = "medium"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"

    llm_base_model: str = "Qwen/Qwen3-1.7B"
    lora_adapter_path: Path = PROJECT_ROOT / "ml/models/qwen3-kpi-lora"
    llm_device: str = "auto"
    classifier_max_new_tokens: int = 128

    @field_validator("audio_storage_dir", "lora_adapter_path", mode="after")
    @classmethod
    def resolve_project_relative_path(cls, value: Path) -> Path:
        if value.is_absolute():
            return value
        return (PROJECT_ROOT / value).resolve()

    @property
    def max_audio_bytes(self) -> int:
        return self.max_audio_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if settings.environment != "development" and settings.jwt_secret_key.startswith("change-this"):
        raise RuntimeError("JWT_SECRET_KEY must be changed outside development.")
    return settings
