from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, utcnow
from app.models.enums import Priority, TicketEventType, TicketStatus

if TYPE_CHECKING:
    from app.models.category import Category
    from app.models.department import Department
    from app.models.model import ModelPrediction
    from app.models.user import User


class Ticket(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "tickets"
    __table_args__ = (
        Index("ix_tickets_status_created_at", "status", "created_at"),
        Index("ix_tickets_assigned_operator_id", "assigned_operator_id"),
        UniqueConstraint("author_id", "client_request_id", name="uq_tickets_author_client_request"),
    )

    author_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )
    status: Mapped[TicketStatus] = mapped_column(
        Enum(TicketStatus, name="ticket_status"),
        default=TicketStatus.draft,
    )
    priority: Mapped[Priority | None] = mapped_column(Enum(Priority, name="ticket_priority"))
    category_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("categories.id", ondelete="SET NULL"),
    )
    department_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("departments.id", ondelete="SET NULL"),
    )
    assigned_operator_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
    )
    client_request_id: Mapped[str | None] = mapped_column(String(80))
    title: Mapped[str | None] = mapped_column(String(180))
    edited_text: Mapped[str | None] = mapped_column(Text)
    model_reason: Mapped[str | None] = mapped_column(Text)
    model_confidence: Mapped[float | None] = mapped_column(Float)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    author: Mapped["User"] = relationship(back_populates="tickets", foreign_keys=[author_id])
    assigned_operator: Mapped["User | None"] = relationship(
        back_populates="assigned_tickets",
        foreign_keys=[assigned_operator_id],
    )
    category: Mapped["Category | None"] = relationship(back_populates="tickets")
    department: Mapped["Department | None"] = relationship(back_populates="tickets")
    audio: Mapped["TicketAudio | None"] = relationship(
        back_populates="ticket",
        uselist=False,
        cascade="all, delete-orphan",
    )
    transcript: Mapped["TicketTranscript | None"] = relationship(
        back_populates="ticket",
        uselist=False,
        cascade="all, delete-orphan",
    )
    messages: Mapped[list["TicketMessage"]] = relationship(
        back_populates="ticket",
        cascade="all, delete-orphan",
    )
    events: Mapped[list["TicketEvent"]] = relationship(
        back_populates="ticket",
        cascade="all, delete-orphan",
    )
    predictions: Mapped[list["ModelPrediction"]] = relationship(
        back_populates="ticket",
        cascade="all, delete-orphan",
    )


class TicketAudio(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ticket_audio"

    ticket_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tickets.id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )
    file_path: Mapped[str] = mapped_column(String(1000))
    original_filename: Mapped[str | None] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int]
    duration_seconds: Mapped[float | None] = mapped_column(Float)

    ticket: Mapped[Ticket] = relationship(back_populates="audio")


class TicketTranscript(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ticket_transcripts"

    ticket_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tickets.id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )
    raw_text: Mapped[str] = mapped_column(Text)
    edited_text: Mapped[str | None] = mapped_column(Text)
    stt_model: Mapped[str] = mapped_column(String(120))
    language: Mapped[str | None] = mapped_column(String(20))

    ticket: Mapped[Ticket] = relationship(back_populates="transcript")


class TicketMessage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ticket_messages"

    ticket_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tickets.id", ondelete="CASCADE"),
        index=True,
    )
    sender_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )
    message: Mapped[str] = mapped_column(Text)
    audio_file_path: Mapped[str | None] = mapped_column(String(1000))
    audio_original_filename: Mapped[str | None] = mapped_column(String(255))
    audio_mime_type: Mapped[str | None] = mapped_column(String(100))
    audio_size_bytes: Mapped[int | None]
    audio_duration_seconds: Mapped[float | None] = mapped_column(Float)
    transcript_text: Mapped[str | None] = mapped_column(Text)
    transcript_model: Mapped[str | None] = mapped_column(String(120))
    transcript_language: Mapped[str | None] = mapped_column(String(20))

    ticket: Mapped[Ticket] = relationship(back_populates="messages")
    sender: Mapped["User"] = relationship(back_populates="messages")


class TicketEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "ticket_events"

    ticket_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tickets.id", ondelete="CASCADE"),
        index=True,
    )
    actor_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
    )
    event_type: Mapped[TicketEventType] = mapped_column(
        Enum(TicketEventType, name="ticket_event_type")
    )
    old_value: Mapped[dict | None] = mapped_column(JSONB)
    new_value: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    ticket: Mapped[Ticket] = relationship(back_populates="events")
    actor: Mapped["User | None"] = relationship(back_populates="events")
