"""add source_id to analysis_runs, schema_catalog and synthetic_datasets

Associates profiling runs, schema-catalog entries and generated datasets with
the registered Source (sources.id) they came from. The column is nullable so
every existing row (legacy demo / uploaded-file flow) stays valid.

Revision ID: a7e1c5b2d904
Revises: 4c2d9a7f1e63
Create Date: 2026-10-11 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a7e1c5b2d904"
down_revision: Union[str, Sequence[str], None] = "4c2d9a7f1e63"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLES = ("analysis_runs", "schema_catalog", "synthetic_datasets")


def upgrade() -> None:
    for table in _TABLES:
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("source_id", sa.String(), nullable=True))
            batch.create_index(f"ix_{table}_source_id", ["source_id"], unique=False)


def downgrade() -> None:
    for table in _TABLES:
        with op.batch_alter_table(table) as batch:
            batch.drop_index(f"ix_{table}_source_id")
            batch.drop_column("source_id")
