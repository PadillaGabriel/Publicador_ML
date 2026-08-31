"""allow one product SKU to be reused across publication categories

Revision ID: 0003_product_reuse_by_sku
Revises: 0002_accounts_financing_exports
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0003_product_reuse_by_sku"
down_revision = "0002_accounts_financing_exports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "product_versions",
        sa.Column(
            "discovery_context",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.alter_column("product_versions", "discovery_context", server_default=None)
    op.drop_column("product_masters", "category_id")


def downgrade() -> None:
    op.add_column(
        "product_masters",
        sa.Column("category_id", sa.String(length=40), nullable=True),
    )
    op.execute(
        """
        UPDATE product_masters pm
        SET category_id = latest.category_id
        FROM (
            SELECT DISTINCT ON (product_master_id)
                   product_master_id, category_id
            FROM product_versions
            ORDER BY product_master_id, version_number DESC
        ) AS latest
        WHERE latest.product_master_id = pm.id
        """
    )
    op.alter_column("product_masters", "category_id", nullable=False)
    op.drop_column("product_versions", "discovery_context")
