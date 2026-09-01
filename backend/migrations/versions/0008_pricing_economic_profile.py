"""add explicit economic pricing profile fields

Revision ID: 0008_pricing_economic_profile
Revises: 0007_pricing_profiles
"""

import sqlalchemy as sa
from alembic import op

revision = "0008_pricing_economic_profile"
down_revision = "0007_pricing_profiles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pricing_profiles",
        sa.Column("vat_rate_pct", sa.Numeric(7, 4), nullable=False, server_default=sa.text("21")),
    )
    for name in ("iibb_rate_pct", "ads_rate_pct", "refund_rate_pct"):
        op.add_column(
            "pricing_profiles",
            sa.Column(name, sa.Numeric(7, 4), nullable=False, server_default=sa.text("0")),
        )
    op.add_column(
        "pricing_cost_components",
        sa.Column(
            "basis",
            sa.String(length=50),
            nullable=False,
            server_default=sa.text("'PRODUCT_COST'"),
        ),
    )

    for name in ("vat_rate_pct", "iibb_rate_pct", "ads_rate_pct", "refund_rate_pct"):
        op.alter_column("pricing_profiles", name, server_default=None)
    op.alter_column("pricing_cost_components", "basis", server_default=None)


def downgrade() -> None:
    op.drop_column("pricing_cost_components", "basis")
    for name in ("refund_rate_pct", "ads_rate_pct", "iibb_rate_pct", "vat_rate_pct"):
        op.drop_column("pricing_profiles", name)
