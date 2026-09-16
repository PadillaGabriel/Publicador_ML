"""add reusable product technical attributes

Revision ID: 0009_product_technical_attributes
Revises: 0008_pricing_economic_profile
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0009_product_technical_attributes"
down_revision = "0008_pricing_economic_profile"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "product_technical_attributes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_master_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("attribute_id", sa.String(length=80), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source_category_id", sa.String(length=40), nullable=True),
        sa.Column("source_kind", sa.String(length=40), nullable=False),
        sa.Column("source_reference", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["product_master_id"],
            ["product_masters.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "product_master_id",
            "attribute_id",
            name="uq_product_technical_attribute",
        ),
    )
    op.create_index(
        "ix_product_technical_attributes_product_master_id",
        "product_technical_attributes",
        ["product_master_id"],
        unique=False,
    )
    op.create_index(
        "ix_product_technical_attributes_attribute_id",
        "product_technical_attributes",
        ["attribute_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_product_technical_attributes_attribute_id",
        table_name="product_technical_attributes",
    )
    op.drop_index(
        "ix_product_technical_attributes_product_master_id",
        table_name="product_technical_attributes",
    )
    op.drop_table("product_technical_attributes")
