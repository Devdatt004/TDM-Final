"""Step 11: sampling metadata on analysis runs and per-column aggregate profiles.

Revision ID: b3e8d1f0a7c2
Revises: c71a9f2e6b40
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "b3e8d1f0a7c2"
down_revision: Union[str, Sequence[str], None] = "c71a9f2e6b40"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("analysis_runs") as batch:
        batch.add_column(sa.Column("sampling_method", sa.String(), nullable=True))
        batch.add_column(sa.Column("sampling_seed", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("stratify_by", sa.String(), nullable=True))
        batch.add_column(sa.Column("population_rows", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("rows_scanned", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("sample_reproducible", sa.Boolean(), nullable=True))
    # Earlier runs all used SELECT ... LIMIT n.
    op.execute("UPDATE analysis_runs SET sampling_method = 'head' WHERE sampling_method IS NULL")

    op.create_table(
        "column_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("column_name", sa.String(), nullable=False),
        sa.Column("metrics_version", sa.String(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["analysis_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "column_name", name="uq_column_profiles_run_column"),
    )
    op.create_index("ix_column_profiles_id", "column_profiles", ["id"], unique=False)
    op.create_index("ix_column_profiles_run_id", "column_profiles", ["run_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_column_profiles_run_id", table_name="column_profiles")
    op.drop_index("ix_column_profiles_id", table_name="column_profiles")
    op.drop_table("column_profiles")
    with op.batch_alter_table("analysis_runs") as batch:
        for name in ("sample_reproducible", "rows_scanned", "population_rows",
                     "stratify_by", "sampling_seed", "sampling_method"):
            batch.drop_column(name)
