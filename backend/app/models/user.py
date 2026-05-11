from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Boolean, Enum, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import UserRole

if TYPE_CHECKING:
    from app.models.auth import RefreshToken
    from app.models.ticket import Ticket, TicketEvent, TicketMessage


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(255))
    student_group: Mapped[str | None] = mapped_column(String(80), nullable=True)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole, name="user_role"), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    tickets: Mapped[list["Ticket"]] = relationship(
        back_populates="author",
        foreign_keys="Ticket.author_id",
    )
    assigned_tickets: Mapped[list["Ticket"]] = relationship(
        back_populates="assigned_operator",
        foreign_keys="Ticket.assigned_operator_id",
    )
    messages: Mapped[list["TicketMessage"]] = relationship(back_populates="sender")
    events: Mapped[list["TicketEvent"]] = relationship(back_populates="actor")
    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(back_populates="user")


UserId = UUID
