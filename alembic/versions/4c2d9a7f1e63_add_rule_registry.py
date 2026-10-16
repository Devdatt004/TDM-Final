"""add rule registry

Revision ID: 4c2d9a7f1e63
Revises: db8fd71119d9
Create Date: 2026-10-09
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "4c2d9a7f1e63"
down_revision: Union[str, Sequence[str], None] = "db8fd71119d9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "rules",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("rule_key", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("rule_type", sa.String(length=50), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("current_version", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=True),
        sa.Column("updated_by", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("deactivated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("rule_key", name="uq_rules_rule_key"),
    )
    op.create_index("ix_rules_id", "rules", ["id"], unique=False)
    op.create_index("ix_rules_name", "rules", ["name"], unique=False)
    op.create_index("ix_rules_rule_type", "rules", ["rule_type"], unique=False)
    op.create_index("ix_rules_status", "rules", ["status"], unique=False)
    op.create_index("ix_rules_created_at", "rules", ["created_at"], unique=False)

    op.create_table(
        "rule_versions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("rule_id", sa.String(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("definition", sa.JSON(), nullable=False),
        sa.Column("change_summary", sa.String(length=1000), nullable=True),
        sa.Column("created_by", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["rule_id"], ["rules.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("rule_id", "version_number", name="uq_rule_versions_rule_version"),
    )
    op.create_index("ix_rule_versions_id", "rule_versions", ["id"], unique=False)
    op.create_index("ix_rule_versions_rule_id", "rule_versions", ["rule_id"], unique=False)
    op.create_index("ix_rule_versions_created_at", "rule_versions", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_rule_versions_created_at", table_name="rule_versions")
    op.drop_index("ix_rule_versions_rule_id", table_name="rule_versions")
    op.drop_index("ix_rule_versions_id", table_name="rule_versions")
    op.drop_table("rule_versions")
    op.drop_index("ix_rules_created_at", table_name="rules")
    op.drop_index("ix_rules_status", table_name="rules")
    op.drop_index("ix_rules_rule_type", table_name="rules")
    op.drop_index("ix_rules_name", table_name="rules")
    op.drop_index("ix_rules_id", table_name="rules")
    op.drop_table("rules")
