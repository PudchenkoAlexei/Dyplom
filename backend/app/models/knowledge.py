from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Enum, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import KnowledgeEntryStatus


class KnowledgeEntry(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "knowledge_entries"
    __table_args__ = (Index("ix_knowledge_entries_status_updated_at", "status", "updated_at"),)

    slug: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(300))
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str] = mapped_column(String(1000), index=True)
    tags_json: Mapped[list[str]] = mapped_column(JSONB, default=list)
    status: Mapped[KnowledgeEntryStatus] = mapped_column(
        Enum(KnowledgeEntryStatus, name="knowledge_entry_status"),
        default=KnowledgeEntryStatus.draft,
        index=True,
    )
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
