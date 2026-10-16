"""Step 13: privacy release status and audited override on synthetic datasets.

Revision ID: e7f3a6b2c9d4
Revises: d5a2c9e4f1b8
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "e7f3a6b2c9d4"
down_revision: Union[str, Sequence[str], None] = "d5a2c9e4f1b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("synthetic_datasets") as batch:
        batch.add_column(sa.Column("release_status", sa.String(), nullable=True))
        batch.add_column(sa.Column("override_by", sa.String(), nullable=True))
        batch.add_column(sa.Column("override_reason", sa.Text(), nullable=True))
        batch.add_column(sa.Column("override_at", sa.DateTime(), nullable=True))
        batch.create_index("ix_synthetic_datasets_release_status", ["release_status"], unique=False)
    # Existing datasets predate the gate; leave release_status NULL ("not assessed")
    # so they keep downloading as before rather than being silently re-labelled.


def downgrade() -> None:
    with op.batch_alter_table("synthetic_datasets") as batch:
        batch.drop_index("ix_synthetic_datasets_release_status")
        for name in ("override_at", "override_reason", "override_by", "release_status"):
            batch.drop_column(name)
