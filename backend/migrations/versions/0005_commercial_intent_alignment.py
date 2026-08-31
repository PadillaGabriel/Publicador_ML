"""align drafts with MLA installments intent instead of fixed installment counts

Revision ID: 0005_commercial_intent_alignment
Revises: 0004_keyword_trend_snapshots
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0005_commercial_intent_alignment"
down_revision = "0004_keyword_trend_snapshots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "draft_batches",
        "installment_distribution",
        new_column_name="commercial_distribution",
        existing_type=postgresql.JSONB(astext_type=sa.Text()),
        existing_nullable=False,
    )
    op.drop_column("publication_drafts", "installments")


def downgrade() -> None:
    op.add_column(
        "publication_drafts",
        sa.Column("installments", sa.Integer(), nullable=False, server_default="1"),
    )
    op.alter_column(
        "draft_batches",
        "commercial_distribution",
        new_column_name="installment_distribution",
        existing_type=postgresql.JSONB(astext_type=sa.Text()),
        existing_nullable=False,
    )
