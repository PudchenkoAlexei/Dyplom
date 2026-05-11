"""add ticket client request id

Revision ID: 0002_ticket_client_request_id
Revises: 0001_initial_schema
Create Date: 2026-05-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_ticket_client_request_id"
down_revision: str | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("tickets", sa.Column("client_request_id", sa.String(length=80), nullable=True))
    op.create_unique_constraint(
        "uq_tickets_author_client_request",
        "tickets",
        ["author_id", "client_request_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_tickets_author_client_request", "tickets", type_="unique")
    op.drop_column("tickets", "client_request_id")
