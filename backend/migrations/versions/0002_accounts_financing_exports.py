"""oauth account metadata and financing distribution

Revision ID: 0002_accounts_financing_exports
Revises: 0001_initial
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002_accounts_financing_exports"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ml_accounts", sa.Column("encrypted_refresh_token", sa.Text(), nullable=True))
    op.add_column("ml_accounts", sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "ml_accounts",
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.add_column("ml_accounts", sa.Column("last_refresh_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "ml_accounts",
        sa.Column("auth_status", sa.String(length=40), nullable=False, server_default="CONNECTED"),
    )
    op.create_index("ix_ml_accounts_auth_status", "ml_accounts", ["auth_status"], unique=False)

    op.add_column(
        "draft_batches",
        sa.Column(
            "installment_distribution",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "publication_drafts",
        sa.Column("installments", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "publication_drafts",
        sa.Column(
            "commercial_config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )

    # Keep future writes application-driven instead of relying on DB defaults.
    op.alter_column("ml_accounts", "connected_at", server_default=None)
    op.alter_column("ml_accounts", "auth_status", server_default=None)
    op.alter_column("draft_batches", "installment_distribution", server_default=None)
    op.alter_column("publication_drafts", "installments", server_default=None)
    op.alter_column("publication_drafts", "commercial_config", server_default=None)


def downgrade() -> None:
    op.drop_column("publication_drafts", "commercial_config")
    op.drop_column("publication_drafts", "installments")
    op.drop_column("draft_batches", "installment_distribution")

    op.drop_index("ix_ml_accounts_auth_status", table_name="ml_accounts")
    op.drop_column("ml_accounts", "auth_status")
    op.drop_column("ml_accounts", "last_refresh_at")
    op.drop_column("ml_accounts", "connected_at")
    op.drop_column("ml_accounts", "token_expires_at")
    op.drop_column("ml_accounts", "encrypted_refresh_token")
