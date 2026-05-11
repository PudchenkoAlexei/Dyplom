"""Add student group to user profiles.

Revision ID: 0003_user_profile_fields
Revises: 0002_ticket_client_request_id
Create Date: 2026-05-11 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0003_user_profile_fields"
down_revision: str | None = "0002_ticket_client_request_id"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("student_group", sa.String(length=80), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "student_group")
