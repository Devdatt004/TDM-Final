"""Step 15: idempotency keys for retried POST/PATCH requests.

Revision ID: f2b8c4d6e1a3
Revises: e7f3a6b2c9d4
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "f2b8c4d6e1a3"
down_revision: Union[str, Sequence[str], None] = "e7f3a6b2c9d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "idempotency_records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("scope", sa.String(64), nullable=False),
        sa.Column("key", sa.String(128), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("response_body", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scope", "key", name="uq_idempotency_scope_key"),
    )
    op.create_index("ix_idempotency_records_created_at", "idempotency_records", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_idempotency_records_created_at", table_name="idempotency_records")
    op.drop_table("idempotency_records")
