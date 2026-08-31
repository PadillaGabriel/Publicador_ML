"""configurable economic pricing profiles

Revision ID: 0007_pricing_profiles
Revises: 0006_worker_heartbeat
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0007_pricing_profiles"
down_revision = "0006_worker_heartbeat"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pricing_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("channel", sa.String(length=40), nullable=False),
        sa.Column("currency_id", sa.String(length=10), nullable=False),
        sa.Column("target_margin_pct", sa.Numeric(7, 4), nullable=False),
        sa.Column("minimum_margin_pct", sa.Numeric(7, 4), nullable=False),
        sa.Column("monthly_units_projection", sa.Integer(), nullable=True),
        sa.Column("rounding_step", sa.Numeric(14, 2), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_pricing_profiles_channel", "pricing_profiles", ["channel"], unique=False)
    op.create_index("ix_pricing_profiles_is_default", "pricing_profiles", ["is_default"], unique=False)
    op.create_index(
        "ix_pricing_profile_default_channel",
        "pricing_profiles",
        ["channel", "is_default"],
        unique=False,
    )

    op.create_table(
        "pricing_cost_components",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("profile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("kind", sa.String(length=50), nullable=False),
        sa.Column("value", sa.Numeric(14, 4), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["profile_id"], ["pricing_profiles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_pricing_cost_components_profile_id", "pricing_cost_components", ["profile_id"], unique=False)
    op.create_index("ix_pricing_cost_components_kind", "pricing_cost_components", ["kind"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_pricing_cost_components_kind", table_name="pricing_cost_components")
    op.drop_index("ix_pricing_cost_components_profile_id", table_name="pricing_cost_components")
    op.drop_table("pricing_cost_components")
    op.drop_index("ix_pricing_profile_default_channel", table_name="pricing_profiles")
    op.drop_index("ix_pricing_profiles_is_default", table_name="pricing_profiles")
    op.drop_index("ix_pricing_profiles_channel", table_name="pricing_profiles")
    op.drop_table("pricing_profiles")
