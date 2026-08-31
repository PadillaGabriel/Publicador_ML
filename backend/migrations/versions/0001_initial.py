"""initial schema (frozen V1 baseline)

Revision ID: 0001_initial
Revises: None
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


metadata = sa.MetaData()
UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB()

sa.Table(
    "ml_accounts", metadata,
    sa.Column("id", UUID, primary_key=True),
    sa.Column("nickname", sa.String(120), nullable=False),
    sa.Column("seller_id", sa.String(80), unique=True, nullable=True),
    sa.Column("site_id", sa.String(10), nullable=False),
    sa.Column("encrypted_access_token", sa.Text(), nullable=False),
    sa.Column("active", sa.Boolean(), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
)

sa.Table(
    "category_metadata_snapshots", metadata,
    sa.Column("id", UUID, primary_key=True),
    sa.Column("site_id", sa.String(10), nullable=False),
    sa.Column("category_id", sa.String(40), nullable=False),
    sa.Column("category_name", sa.String(255), nullable=False),
    sa.Column("raw_category", JSONB, nullable=False),
    sa.Column("raw_attributes", JSONB, nullable=False),
    sa.Column("normalized_schema", JSONB, nullable=False),
    sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    sa.Index("ix_category_metadata_latest", "site_id", "category_id", "fetched_at"),
)

sa.Table(
    "product_masters", metadata,
    sa.Column("id", UUID, primary_key=True),
    sa.Column("internal_sku", sa.String(120), unique=True, nullable=False),
    sa.Column("internal_name", sa.String(255), nullable=False),
    sa.Column("category_id", sa.String(40), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
)

sa.Table(
    "product_versions", metadata,
    sa.Column("id", UUID, primary_key=True),
    sa.Column("product_master_id", UUID, sa.ForeignKey("product_masters.id", ondelete="CASCADE"), nullable=False, index=True),
    sa.Column("version_number", sa.Integer(), nullable=False),
    sa.Column("category_id", sa.String(40), nullable=False),
    sa.Column("title_reference", sa.String(255), nullable=False),
    sa.Column("description", sa.Text(), nullable=False),
    sa.Column("price", sa.Numeric(14, 2), nullable=False),
    sa.Column("quantity", sa.Integer(), nullable=False),
    sa.Column("condition", sa.String(40), nullable=False),
    sa.Column("currency_id", sa.String(10), nullable=False),
    sa.Column("listing_type_id", sa.String(40), nullable=True),
    sa.Column("attributes", JSONB, nullable=False),
    sa.Column("commercial", JSONB, nullable=False),
    sa.Column("logistics", JSONB, nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.UniqueConstraint("product_master_id", "version_number", name="uq_product_version"),
)

sa.Table(
    "product_images", metadata,
    sa.Column("id", UUID, primary_key=True),
    sa.Column("product_version_id", UUID, sa.ForeignKey("product_versions.id", ondelete="CASCADE"), nullable=False, index=True),
    sa.Column("original_name", sa.String(255), nullable=False),
    sa.Column("storage_path", sa.Text(), nullable=False),
    sa.Column("mime_type", sa.String(100), nullable=False),
    sa.Column("position", sa.Integer(), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
)

sa.Table(
    "keyword_snapshots", metadata,
    sa.Column("id", UUID, primary_key=True),
    sa.Column("product_version_id", UUID, sa.ForeignKey("product_versions.id", ondelete="CASCADE"), nullable=False, index=True),
    sa.Column("strategy_version", sa.String(40), nullable=False),
    sa.Column("keywords", JSONB, nullable=False),
    sa.Column("evidence", JSONB, nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
)

sa.Table(
    "title_generation_runs", metadata,
    sa.Column("id", UUID, primary_key=True),
    sa.Column("keyword_snapshot_id", UUID, sa.ForeignKey("keyword_snapshots.id", ondelete="CASCADE"), nullable=False, index=True),
    sa.Column("model", sa.String(120), nullable=False),
    sa.Column("prompt_version", sa.String(50), nullable=False),
    sa.Column("requested_count", sa.Integer(), nullable=False),
    sa.Column("provider_request_id", sa.String(255), nullable=True),
    sa.Column("usage", JSONB, nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
)

sa.Table(
    "draft_batches", metadata,
    sa.Column("id", UUID, primary_key=True),
    sa.Column("product_version_id", UUID, sa.ForeignKey("product_versions.id", ondelete="RESTRICT"), nullable=False, index=True),
    sa.Column("account_id", UUID, sa.ForeignKey("ml_accounts.id", ondelete="RESTRICT"), nullable=False, index=True),
    sa.Column("requested_count", sa.Integer(), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
)

sa.Table(
    "publication_drafts", metadata,
    sa.Column("id", UUID, primary_key=True),
    sa.Column("batch_id", UUID, sa.ForeignKey("draft_batches.id", ondelete="CASCADE"), nullable=False, index=True),
    sa.Column("sequence_number", sa.Integer(), nullable=False),
    sa.Column("title", sa.String(255), nullable=False),
    sa.Column("title_score", sa.Integer(), nullable=False),
    sa.Column("status", sa.String(40), nullable=False, index=True),
    sa.Column("image_order", JSONB, nullable=False),
    sa.Column("title_generation_run_id", UUID, sa.ForeignKey("title_generation_runs.id"), nullable=True),
    sa.Column("idempotency_key", sa.String(128), unique=True, nullable=False),
    sa.Column("last_error", JSONB, nullable=True),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    sa.UniqueConstraint("batch_id", "sequence_number", name="uq_draft_sequence"),
)

sa.Table(
    "validation_results", metadata,
    sa.Column("id", UUID, primary_key=True),
    sa.Column("draft_id", UUID, sa.ForeignKey("publication_drafts.id", ondelete="CASCADE"), nullable=False, index=True),
    sa.Column("valid", sa.Boolean(), nullable=False),
    sa.Column("errors", JSONB, nullable=False),
    sa.Column("warnings", JSONB, nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
)

sa.Table(
    "publications", metadata,
    sa.Column("id", UUID, primary_key=True),
    sa.Column("draft_id", UUID, sa.ForeignKey("publication_drafts.id", ondelete="RESTRICT"), unique=True, nullable=False, index=True),
    sa.Column("account_id", UUID, sa.ForeignKey("ml_accounts.id", ondelete="RESTRICT"), nullable=False, index=True),
    sa.Column("status", sa.String(40), nullable=False),
    sa.Column("item_id", sa.String(80), nullable=True, index=True),
    sa.Column("user_product_id", sa.String(80), nullable=True, index=True),
    sa.Column("external_response", JSONB, nullable=False),
    sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
)

sa.Table(
    "publication_attempts", metadata,
    sa.Column("id", UUID, primary_key=True),
    sa.Column("draft_id", UUID, sa.ForeignKey("publication_drafts.id", ondelete="CASCADE"), nullable=False, index=True),
    sa.Column("attempt_number", sa.Integer(), nullable=False),
    sa.Column("request_payload", JSONB, nullable=False),
    sa.Column("response_payload", JSONB, nullable=True),
    sa.Column("http_status", sa.Integer(), nullable=True),
    sa.Column("outcome", sa.String(50), nullable=False),
    sa.Column("retryable", sa.Boolean(), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
)

sa.Table(
    "jobs", metadata,
    sa.Column("id", UUID, primary_key=True),
    sa.Column("type", sa.String(50), nullable=False),
    sa.Column("status", sa.String(40), nullable=False, index=True),
    sa.Column("total", sa.Integer(), nullable=False),
    sa.Column("processed", sa.Integer(), nullable=False),
    sa.Column("succeeded", sa.Integer(), nullable=False),
    sa.Column("failed", sa.Integer(), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
)

sa.Table(
    "job_items", metadata,
    sa.Column("id", UUID, primary_key=True),
    sa.Column("job_id", UUID, sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True),
    sa.Column("draft_id", UUID, sa.ForeignKey("publication_drafts.id", ondelete="RESTRICT"), nullable=False, index=True),
    sa.Column("status", sa.String(40), nullable=False, index=True),
    sa.Column("attempts", sa.Integer(), nullable=False),
    sa.Column("last_error", JSONB, nullable=True),
    sa.UniqueConstraint("job_id", "draft_id", name="uq_job_draft"),
)

sa.Table(
    "audit_events", metadata,
    sa.Column("id", UUID, primary_key=True),
    sa.Column("event_type", sa.String(100), nullable=False, index=True),
    sa.Column("entity_type", sa.String(80), nullable=False),
    sa.Column("entity_id", sa.String(120), nullable=False, index=True),
    sa.Column("payload", JSONB, nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
)


def upgrade() -> None:
    metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    metadata.drop_all(bind=op.get_bind())
