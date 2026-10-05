"""Attribute newly created publication jobs to their operator.

Revision ID: 0012_job_requester
Revises: 0011_product_ownership
Legacy jobs remain NULL; no fabricated authorship.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0012_job_requester"
down_revision = "0011_product_ownership"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("requested_by_user_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_jobs_requested_by_user", "jobs", "operator_users",
        ["requested_by_user_id"], ["id"], ondelete="SET NULL",
    )
    op.create_index("ix_jobs_requested_by_user_id", "jobs", ["requested_by_user_id"])


def downgrade() -> None:
    op.drop_index("ix_jobs_requested_by_user_id", table_name="jobs")
    op.drop_constraint("fk_jobs_requested_by_user", "jobs", type_="foreignkey")
    op.drop_column("jobs", "requested_by_user_id")
