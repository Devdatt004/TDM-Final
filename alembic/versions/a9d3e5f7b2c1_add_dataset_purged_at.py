"""Step 16: record when the retention purge deleted a dataset file.

Revision ID: a9d3e5f7b2c1
Revises: f2b8c4d6e1a3
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "a9d3e5f7b2c1"
down_revision: Union[str, Sequence[str], None] = "f2b8c4d6e1a3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("synthetic_datasets") as batch:
        batch.add_column(sa.Column("purged_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("synthetic_datasets") as batch:
        batch.drop_column("purged_at")
