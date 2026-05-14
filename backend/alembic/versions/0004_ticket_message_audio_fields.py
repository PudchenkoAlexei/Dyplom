"""add audio fields to ticket messages

Revision ID: 0004_ticket_message_audio_fields
Revises: 0003_user_profile_fields
Create Date: 2026-05-14

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_ticket_message_audio_fields"
down_revision: str | None = "0003_user_profile_fields"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ticket_messages",
        sa.Column("audio_file_path", sa.String(length=1000), nullable=True),
    )
    op.add_column(
        "ticket_messages",
        sa.Column("audio_original_filename", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "ticket_messages",
        sa.Column("audio_mime_type", sa.String(length=100), nullable=True),
    )
    op.add_column("ticket_messages", sa.Column("audio_size_bytes", sa.Integer(), nullable=True))
    op.add_column(
        "ticket_messages",
        sa.Column("audio_duration_seconds", sa.Float(), nullable=True),
    )
    op.add_column("ticket_messages", sa.Column("transcript_text", sa.Text(), nullable=True))
    op.add_column(
        "ticket_messages",
        sa.Column("transcript_model", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "ticket_messages",
        sa.Column("transcript_language", sa.String(length=20), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ticket_messages", "transcript_language")
    op.drop_column("ticket_messages", "transcript_model")
    op.drop_column("ticket_messages", "transcript_text")
    op.drop_column("ticket_messages", "audio_duration_seconds")
    op.drop_column("ticket_messages", "audio_size_bytes")
    op.drop_column("ticket_messages", "audio_mime_type")
    op.drop_column("ticket_messages", "audio_original_filename")
    op.drop_column("ticket_messages", "audio_file_path")
