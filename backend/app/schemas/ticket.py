from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.enums import Priority, TicketEventType, TicketStatus, UserRole
from app.schemas.catalog import CategoryRead, DepartmentRead
from app.schemas.common import ORMModel, Timestamped
from app.schemas.user import UserRead


class TicketAudioRead(Timestamped):
    id: UUID
    mime_type: str
    size_bytes: int
    duration_seconds: float | None


class TicketTranscriptRead(Timestamped):
    id: UUID
    raw_text: str
    edited_text: str | None
    stt_model: str
    language: str | None


class TicketMessageCreate(BaseModel):
    message: str = Field(min_length=1, max_length=8000)


class TicketMessageRead(Timestamped):
    id: UUID
    sender_id: UUID
    message: str


class TicketEventRead(ORMModel):
    id: UUID
    actor_id: UUID | None
    event_type: TicketEventType
    old_value: dict | None
    new_value: dict | None
    created_at: datetime


class TicketTextUpdate(BaseModel):
    edited_text: str = Field(min_length=3, max_length=12000)


class TicketClassificationUpdate(BaseModel):
    category_id: UUID
    department_id: UUID
    priority: Priority
    reason: str | None = Field(default=None, max_length=2000)


class TicketRead(Timestamped):
    id: UUID
    author_id: UUID
    author: UserRead | None = None
    status: TicketStatus
    priority: Priority | None
    title: str | None
    edited_text: str | None
    model_reason: str | None
    model_confidence: float | None
    closed_at: datetime | None
    assigned_operator_id: UUID | None
    assigned_operator: UserRead | None = None
    category: CategoryRead | None
    department: DepartmentRead | None
    audio: TicketAudioRead | None
    transcript: TicketTranscriptRead | None
    messages: list[TicketMessageRead] = Field(default_factory=list)
    events: list[TicketEventRead] = Field(default_factory=list)


class TicketListItem(Timestamped):
    id: UUID
    author_id: UUID
    status: TicketStatus
    priority: Priority | None
    title: str | None
    edited_text: str | None
    model_confidence: float | None
    assigned_operator_id: UUID | None
    assigned_operator: UserRead | None = None
    category: CategoryRead | None
    department: DepartmentRead | None


class DraftTicketResponse(BaseModel):
    ticket: TicketRead
    transcript_text: str


class OperatorTicketRead(TicketRead):
    author: UserRead


class TicketFilter(BaseModel):
    status: TicketStatus | None = None
    assigned_to_me: bool | None = None
    role: UserRole | None = None
