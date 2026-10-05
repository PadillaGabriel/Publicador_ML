"""Record authorship without inventing an owner for historical product masters.

Revision ID: 0011_product_ownership
Revises: 0010_operator_identity
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0011_product_ownership"
down_revision = "0010_operator_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("product_masters", sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("fk_product_master_creator", "product_masters", "operator_users", ["created_by_user_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_product_masters_created_by_user_id", "product_masters", ["created_by_user_id"])


def downgrade() -> None:
    op.drop_index("ix_product_masters_created_by_user_id", table_name="product_masters")
    op.drop_constraint("fk_product_master_creator", "product_masters", type_="foreignkey")
    op.drop_column("product_masters", "created_by_user_id")
