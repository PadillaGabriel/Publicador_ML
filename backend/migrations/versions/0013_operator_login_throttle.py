"""Persistent failed-login counters. Revision ID: 0013_operator_login_throttle."""

import sqlalchemy as sa
from alembic import op

revision = "0013_operator_login_throttle"
down_revision = "0012_job_requester"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "operator_login_failures",
        sa.Column("username_hash", sa.String(length=64), primary_key=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("blocked_until", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("attempts >= 1", name="ck_operator_login_failure_attempts"),
    )


def downgrade() -> None:
    op.drop_table("operator_login_failures")
