from __future__ import annotations

from sqlalchemy import Float, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class PhoneAssistantCall(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "phone_assistant_calls"

    call_id: Mapped[str] = mapped_column(String(160), index=True)
    caller_number: Mapped[str | None] = mapped_column(String(80), nullable=True)
    question_audio_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    question_audio_mime_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    question_audio_size_bytes: Mapped[int | None]
    question_text: Mapped[str] = mapped_column(Text)
    answer_text: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(80))
    sources_json: Mapped[list[dict] | None] = mapped_column(JSONB)
    used_llm: Mapped[bool]
    model_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
