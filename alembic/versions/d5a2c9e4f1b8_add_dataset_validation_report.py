"""Step 12/13: release-gate evidence on synthetic datasets.

Revision ID: d5a2c9e4f1b8
Revises: b3e8d1f0a7c2
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "d5a2c9e4f1b8"
down_revision: Union[str, Sequence[str], None] = "b3e8d1f0a7c2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("synthetic_datasets") as batch:
        batch.add_column(sa.Column("validation_report", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("synthetic_datasets") as batch:
        batch.drop_column("validation_report")
