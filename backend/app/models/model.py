from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Enum, Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import Priority

if TYPE_CHECKING:
    from app.models.ticket import Ticket


class ModelVersion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "model_versions"

    name: Mapped[str] = mapped_column(String(160), unique=True)
    base_model: Mapped[str] = mapped_column(String(255))
    lora_adapter_path: Mapped[str] = mapped_column(String(1000))
    dataset_version: Mapped[str | None] = mapped_column(String(120))
    metrics_json: Mapped[dict | None] = mapped_column(JSONB)

    predictions: Mapped[list["ModelPrediction"]] = relationship(back_populates="model_version")


class ModelPrediction(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "model_predictions"

    ticket_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tickets.id", ondelete="CASCADE"),
        index=True,
    )
    model_version_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("model_versions.id", ondelete="SET NULL"),
    )
    category_name: Mapped[str] = mapped_column(String(120))
    department_name: Mapped[str] = mapped_column(String(255))
    priority: Mapped[Priority] = mapped_column(Enum(Priority, name="ticket_priority"))
    confidence: Mapped[float] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(Text)
    raw_output: Mapped[dict | None] = mapped_column(JSONB)

    ticket: Mapped["Ticket"] = relationship(back_populates="predictions")
    model_version: Mapped["ModelVersion | None"] = relationship(back_populates="predictions")
