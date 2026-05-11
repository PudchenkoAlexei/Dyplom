"""initial schema

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-05-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    user_role = postgresql.ENUM("student", "teacher", "operator", "admin", name="user_role")
    ticket_status = postgresql.ENUM(
        "draft",
        "submitted",
        "classified",
        "in_progress",
        "waiting_user",
        "answered",
        "closed",
        name="ticket_status",
    )
    ticket_priority = postgresql.ENUM("low", "medium", "high", name="ticket_priority")
    ticket_event_type = postgresql.ENUM(
        "created",
        "audio_uploaded",
        "transcribed",
        "edited",
        "submitted",
        "classified",
        "claimed",
        "classification_changed",
        "message_sent",
        "status_changed",
        "closed",
        name="ticket_event_type",
    )

    bind = op.get_bind()
    user_role.create(bind, checkfirst=True)
    ticket_status.create(bind, checkfirst=True)
    ticket_priority.create(bind, checkfirst=True)
    ticket_event_type.create(bind, checkfirst=True)

    user_role = postgresql.ENUM("student", "teacher", "operator", "admin", name="user_role", create_type=False)
    ticket_status = postgresql.ENUM(
        "draft",
        "submitted",
        "classified",
        "in_progress",
        "waiting_user",
        "answered",
        "closed",
        name="ticket_status",
        create_type=False,
    )
    ticket_priority = postgresql.ENUM(
        "low",
        "medium",
        "high",
        name="ticket_priority",
        create_type=False,
    )
    ticket_event_type = postgresql.ENUM(
        "created",
        "audio_uploaded",
        "transcribed",
        "edited",
        "submitted",
        "classified",
        "claimed",
        "classification_changed",
        "message_sent",
        "status_changed",
        "closed",
        name="ticket_event_type",
        create_type=False,
    )

    op.create_table(
        "departments",
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("contact_url", sa.String(length=500), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_departments_name"), "departments", ["name"], unique=True)

    op.create_table(
        "users",
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("role", user_role, nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)
    op.create_index(op.f("ix_users_role"), "users", ["role"], unique=False)

    op.create_table(
        "categories",
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("default_department_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["default_department_id"],
            ["departments.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_categories_name"), "categories", ["name"], unique=True)

    op.create_table(
        "model_versions",
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("base_model", sa.String(length=255), nullable=False),
        sa.Column("lora_adapter_path", sa.String(length=1000), nullable=False),
        sa.Column("dataset_version", sa.String(length=120), nullable=True),
        sa.Column("metrics_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    op.create_table(
        "refresh_tokens",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_refresh_tokens_token_hash"), "refresh_tokens", ["token_hash"], unique=True)
    op.create_index(op.f("ix_refresh_tokens_user_id"), "refresh_tokens", ["user_id"], unique=False)

    op.create_table(
        "tickets",
        sa.Column("author_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", ticket_status, nullable=False),
        sa.Column("priority", ticket_priority, nullable=True),
        sa.Column("category_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("department_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("assigned_operator_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.String(length=180), nullable=True),
        sa.Column("edited_text", sa.Text(), nullable=True),
        sa.Column("model_reason", sa.Text(), nullable=True),
        sa.Column("model_confidence", sa.Float(), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["assigned_operator_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["author_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["category_id"], ["categories.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["department_id"], ["departments.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tickets_assigned_operator_id", "tickets", ["assigned_operator_id"], unique=False)
    op.create_index(op.f("ix_tickets_author_id"), "tickets", ["author_id"], unique=False)
    op.create_index("ix_tickets_status_created_at", "tickets", ["status", "created_at"], unique=False)

    op.create_table(
        "model_predictions",
        sa.Column("ticket_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("model_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("category_name", sa.String(length=120), nullable=False),
        sa.Column("department_name", sa.String(length=255), nullable=False),
        sa.Column("priority", ticket_priority, nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("raw_output", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["model_version_id"], ["model_versions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_model_predictions_ticket_id"), "model_predictions", ["ticket_id"], unique=False)

    op.create_table(
        "ticket_audio",
        sa.Column("ticket_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("file_path", sa.String(length=1000), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=True),
        sa.Column("mime_type", sa.String(length=100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_ticket_audio_ticket_id"), "ticket_audio", ["ticket_id"], unique=True)

    op.create_table(
        "ticket_events",
        sa.Column("ticket_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("event_type", ticket_event_type, nullable=False),
        sa.Column("old_value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("new_value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_ticket_events_actor_id"), "ticket_events", ["actor_id"], unique=False)
    op.create_index(op.f("ix_ticket_events_ticket_id"), "ticket_events", ["ticket_id"], unique=False)

    op.create_table(
        "ticket_messages",
        sa.Column("ticket_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sender_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["sender_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_ticket_messages_sender_id"), "ticket_messages", ["sender_id"], unique=False)
    op.create_index(op.f("ix_ticket_messages_ticket_id"), "ticket_messages", ["ticket_id"], unique=False)

    op.create_table(
        "ticket_transcripts",
        sa.Column("ticket_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("edited_text", sa.Text(), nullable=True),
        sa.Column("stt_model", sa.String(length=120), nullable=False),
        sa.Column("language", sa.String(length=20), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_ticket_transcripts_ticket_id"), "ticket_transcripts", ["ticket_id"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_ticket_transcripts_ticket_id"), table_name="ticket_transcripts")
    op.drop_table("ticket_transcripts")
    op.drop_index(op.f("ix_ticket_messages_ticket_id"), table_name="ticket_messages")
    op.drop_index(op.f("ix_ticket_messages_sender_id"), table_name="ticket_messages")
    op.drop_table("ticket_messages")
    op.drop_index(op.f("ix_ticket_events_ticket_id"), table_name="ticket_events")
    op.drop_index(op.f("ix_ticket_events_actor_id"), table_name="ticket_events")
    op.drop_table("ticket_events")
    op.drop_index(op.f("ix_ticket_audio_ticket_id"), table_name="ticket_audio")
    op.drop_table("ticket_audio")
    op.drop_index(op.f("ix_model_predictions_ticket_id"), table_name="model_predictions")
    op.drop_table("model_predictions")
    op.drop_index("ix_tickets_status_created_at", table_name="tickets")
    op.drop_index(op.f("ix_tickets_author_id"), table_name="tickets")
    op.drop_index("ix_tickets_assigned_operator_id", table_name="tickets")
    op.drop_table("tickets")
    op.drop_index(op.f("ix_refresh_tokens_user_id"), table_name="refresh_tokens")
    op.drop_index(op.f("ix_refresh_tokens_token_hash"), table_name="refresh_tokens")
    op.drop_table("refresh_tokens")
    op.drop_table("model_versions")
    op.drop_index(op.f("ix_categories_name"), table_name="categories")
    op.drop_table("categories")
    op.drop_index(op.f("ix_users_role"), table_name="users")
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")
    op.drop_index(op.f("ix_departments_name"), table_name="departments")
    op.drop_table("departments")

    bind = op.get_bind()
    postgresql.ENUM(name="ticket_event_type").drop(bind, checkfirst=True)
    postgresql.ENUM(name="ticket_priority").drop(bind, checkfirst=True)
    postgresql.ENUM(name="ticket_status").drop(bind, checkfirst=True)
    postgresql.ENUM(name="user_role").drop(bind, checkfirst=True)
