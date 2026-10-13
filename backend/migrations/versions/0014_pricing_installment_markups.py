"""Add configurable 3/6 installment price markups.

Revision ID: 0014_pricing_installment_markups
Revises: 0013_operator_login_throttle
"""

import sqlalchemy as sa
from alembic import op

revision = "0014_pricing_installment_markups"
down_revision = "0013_operator_login_throttle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pricing_profiles",
        sa.Column(
            "installment_3_markup_pct",
            sa.Numeric(7, 4),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "pricing_profiles",
        sa.Column(
            "installment_6_markup_pct",
            sa.Numeric(7, 4),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.alter_column("pricing_profiles", "installment_3_markup_pct", server_default=None)
    op.alter_column("pricing_profiles", "installment_6_markup_pct", server_default=None)


def downgrade() -> None:
    op.drop_column("pricing_profiles", "installment_6_markup_pct")
    op.drop_column("pricing_profiles", "installment_3_markup_pct")
