"""Introduce operator identities and temporary edit leases; no access cutover yet.

Revision ID: 0010_operator_identity
Revises: 0009_technical_attributes
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0010_operator_identity"
down_revision = "0009_technical_attributes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "operator_users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("username", sa.String(120), nullable=False, unique=True),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("display_name", sa.String(160), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("role IN ('ADMIN', 'SUPERVISOR', 'OPERATOR')", name="ck_operator_user_role"),
    )
    op.create_table(
        "operator_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("operator_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_operator_sessions_user_expires", "operator_sessions", ["user_id", "expires_at"])
    op.create_table(
        "operator_account_grants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("operator_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ml_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.UniqueConstraint("user_id", "account_id", name="uq_operator_account_grant"),
    )
    op.create_table(
        "product_edit_leases",
        sa.Column("product_master_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("product_masters.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("operator_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("operator_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("fencing_token", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.add_column("audit_events", sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("fk_audit_actor_user", "audit_events", "operator_users", ["actor_user_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_audit_events_actor_user_id", "audit_events", ["actor_user_id"])


def downgrade() -> None:
    op.drop_index("ix_audit_events_actor_user_id", table_name="audit_events")
    op.drop_constraint("fk_audit_actor_user", "audit_events", type_="foreignkey")
    op.drop_column("audit_events", "actor_user_id")
    op.drop_table("product_edit_leases")
    op.drop_table("operator_account_grants")
    op.drop_index("ix_operator_sessions_user_expires", table_name="operator_sessions")
    op.drop_table("operator_sessions")
    op.drop_table("operator_users")
