"""add phone assistant call logs

Revision ID: 0005_phone_assistant_calls
Revises: 0004_ticket_message_audio_fields
Create Date: 2026-05-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_phone_assistant_calls"
down_revision: str | None = "0004_ticket_message_audio_fields"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "phone_assistant_calls",
        sa.Column("call_id", sa.String(length=160), nullable=False),
        sa.Column("caller_number", sa.String(length=80), nullable=True),
        sa.Column("question_audio_path", sa.String(length=1000), nullable=True),
        sa.Column("question_audio_mime_type", sa.String(length=100), nullable=True),
        sa.Column("question_audio_size_bytes", sa.Integer(), nullable=True),
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column("answer_text", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("source", sa.String(length=80), nullable=False),
        sa.Column("sources_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("used_llm", sa.Boolean(), nullable=False),
        sa.Column("model_name", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_phone_assistant_calls_call_id"),
        "phone_assistant_calls",
        ["call_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_phone_assistant_calls_call_id"), table_name="phone_assistant_calls")
    op.drop_table("phone_assistant_calls")
