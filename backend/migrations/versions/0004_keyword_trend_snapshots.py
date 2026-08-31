"""cache Mercado Libre category trends for keyword intelligence

Revision ID: 0004_keyword_trend_snapshots
Revises: 0003_product_reuse_by_sku
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0004_keyword_trend_snapshots"
down_revision = "0003_product_reuse_by_sku"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "keyword_trend_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("site_id", sa.String(length=10), nullable=False),
        sa.Column("category_id", sa.String(length=40), nullable=False),
        sa.Column("source", sa.String(length=80), nullable=False),
        sa.Column("terms", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_keyword_trends_latest",
        "keyword_trend_snapshots",
        ["site_id", "category_id", "fetched_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_keyword_trends_latest", table_name="keyword_trend_snapshots")
    op.drop_table("keyword_trend_snapshots")
