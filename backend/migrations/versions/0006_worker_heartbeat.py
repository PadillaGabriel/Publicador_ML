"""persist worker liveness for durable publication jobs

Revision ID: 0006_worker_heartbeat
Revises: 0005_commercial_intent_alignment
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0006_worker_heartbeat"
down_revision = "0005_commercial_intent_alignment"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "worker_heartbeats",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("instance_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(length=50), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_worker_heartbeats_instance_id", "worker_heartbeats", ["instance_id"], unique=True)
    op.create_index("ix_worker_heartbeats_role", "worker_heartbeats", ["role"], unique=False)
    op.create_index("ix_worker_heartbeats_heartbeat_at", "worker_heartbeats", ["heartbeat_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_worker_heartbeats_heartbeat_at", table_name="worker_heartbeats")
    op.drop_index("ix_worker_heartbeats_role", table_name="worker_heartbeats")
    op.drop_index("ix_worker_heartbeats_instance_id", table_name="worker_heartbeats")
    op.drop_table("worker_heartbeats")
