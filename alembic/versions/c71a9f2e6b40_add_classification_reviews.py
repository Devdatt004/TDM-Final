"""Add persistent human classification review queue.

Revision ID: c71a9f2e6b40
Revises: 13500d4e7095
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "c71a9f2e6b40"
down_revision: Union[str, Sequence[str], None] = "13500d4e7095"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "classification_reviews",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("classification_result_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="PENDING"),
        sa.Column("proposed_pattern_type", sa.String(), nullable=True),
        sa.Column("proposed_sensitivity", sa.String(), nullable=False, server_default="unknown"),
        sa.Column("final_pattern_type", sa.String(), nullable=True),
        sa.Column("final_sensitivity", sa.String(), nullable=True),
        sa.Column("reviewer_user_id", sa.String(), nullable=True),
        sa.Column("reviewer_username", sa.String(), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["classification_result_id"], ["classification_results.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_classification_reviews_id", "classification_reviews", ["id"], unique=False)
    op.create_index("ix_classification_reviews_status", "classification_reviews", ["status"], unique=False)
    op.create_index("ix_classification_reviews_classification_result_id", "classification_reviews", ["classification_result_id"], unique=True)
    op.create_index("ix_classification_reviews_created_at", "classification_reviews", ["created_at"], unique=False)
    # Existing flagged classifications must enter the queue when upgrading.
    op.execute("""
        INSERT INTO classification_reviews
            (classification_result_id, status, proposed_pattern_type, proposed_sensitivity, created_at)
        SELECT id, 'PENDING', pattern_type, sensitivity, CURRENT_TIMESTAMP
        FROM classification_results
        WHERE review_required = TRUE
    """)


def downgrade() -> None:
    op.drop_index("ix_classification_reviews_created_at", table_name="classification_reviews")
    op.drop_index("ix_classification_reviews_classification_result_id", table_name="classification_reviews")
    op.drop_index("ix_classification_reviews_status", table_name="classification_reviews")
    op.drop_index("ix_classification_reviews_id", table_name="classification_reviews")
    op.drop_table("classification_reviews")
