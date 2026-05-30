"""add managed knowledge base table

Revision ID: 0006_knowledge_base_admin
Revises: 0005_phone_assistant_calls
Create Date: 2026-05-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_knowledge_base_admin"
down_revision: str | None = "0005_phone_assistant_calls"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    entry_status = postgresql.ENUM(
        "draft",
        "published",
        "archived",
        name="knowledge_entry_status",
    )

    bind = op.get_bind()
    entry_status.create(bind, checkfirst=True)

    entry_status = postgresql.ENUM(
        "draft",
        "published",
        "archived",
        name="knowledge_entry_status",
        create_type=False,
    )

    op.create_table(
        "knowledge_entries",
        sa.Column("slug", sa.String(length=160), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("source_url", sa.String(length=1000), nullable=False),
        sa.Column("tags_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", entry_status, nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_knowledge_entries_slug"), "knowledge_entries", ["slug"], unique=True)
    op.create_index(
        op.f("ix_knowledge_entries_source_url"),
        "knowledge_entries",
        ["source_url"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_entries_status"),
        "knowledge_entries",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_knowledge_entries_status_updated_at",
        "knowledge_entries",
        ["status", "updated_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_entries_content_hash"),
        "knowledge_entries",
        ["content_hash"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_knowledge_entries_content_hash"), table_name="knowledge_entries")
    op.drop_index("ix_knowledge_entries_status_updated_at", table_name="knowledge_entries")
    op.drop_index(op.f("ix_knowledge_entries_status"), table_name="knowledge_entries")
    op.drop_index(op.f("ix_knowledge_entries_source_url"), table_name="knowledge_entries")
    op.drop_index(op.f("ix_knowledge_entries_slug"), table_name="knowledge_entries")
    op.drop_table("knowledge_entries")

    bind = op.get_bind()
    postgresql.ENUM(name="knowledge_entry_status").drop(bind, checkfirst=True)
